"""
Session management and memory orchestration.

This service encapsulates common operations around session ID resolution,
cookie semantics, and conversation memory (history/persona/scene and
AIMS-related snapshots). It is intentionally lightweight and keeps parity
with existing behavior in app.main.

Design goals:
- Pure-Python, no FastAPI dependency (accept request-like objects when needed)
- Easy to unit test and mock
- No behavior changes vs. existing main.py logic
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple
import time
import uuid


@dataclass(frozen=True)
class CookieSettings:
    name: str
    secure: bool
    samesite: str
    max_age: int


class SessionService:
    def __init__(
        self,
        store: Any,
        *,
        cookie: CookieSettings,
        memory_enabled: bool,
        memory_max_turns: int,
        memory_ttl_seconds: int,
    ) -> None:
        self._store = store
        self.cookie = cookie
        self.memory_enabled = memory_enabled
        self.memory_max_turns = int(memory_max_turns)
        self.memory_ttl_seconds = int(memory_ttl_seconds)

    # -------- Session ID handling --------
    def ensure_session(self, request, body_session_id: Optional[str]) -> Tuple[str, bool]:
        """Resolve or create a session id.
        Order: body.sessionId -> cookie -> generate new.
        Returns (session_id, set_cookie_flag).
        """
        sid = body_session_id or (getattr(request, "cookies", {}) or {}).get(self.cookie.name)
        generated = False
        if not sid:
            sid = str(uuid.uuid4())
            generated = True
        # Initialize memory record if enabled
        if self.memory_enabled:
            now = time.time()
            mem = self._store.get(sid)
            if not mem:
                mem = {"history": [], "character": None, "scene": None, "updated": now}
                self._store[sid] = mem
            else:
                # touch updated lazily; callers also update as needed
                mem.setdefault("updated", now)
        return sid, generated

    # -------- Memory helpers --------
    def get_mem(self, session_id: str) -> dict:
        if not (self.memory_enabled and session_id):
            return {}
        return self._store.get(session_id) or {}

    def save_mem(self, session_id: str, mem: dict) -> None:
        if not (self.memory_enabled and session_id):
            return
        mem["updated"] = time.time()
        self._store[session_id] = mem

    def update_persona_scene(self, session_id: str, character: Optional[str], scene: Optional[str]) -> dict:
        if not (self.memory_enabled and session_id):
            return {}
        now = time.time()
        mem = self._store.get(session_id) or {"history": [], "character": None, "scene": None, "updated": now}
        if character:
            mem["character"] = character.strip()
        if scene:
            mem["scene"] = scene.strip()
        mem["updated"] = now
        self._store[session_id] = mem
        return mem

    def append_history(self, session_id: str, role: str, content: str) -> None:
        if not (self.memory_enabled and session_id):
            return
        mem = self._store.get(session_id) or {"history": [], "character": None, "scene": None, "updated": time.time()}
        mem.setdefault("history", []).append({"role": role, "content": content})
        # Trim to last N pairs (user+assistant)
        max_items = self.memory_max_turns * 2
        if len(mem["history"]) > max_items:
            mem["history"] = mem["history"][ - max_items:]
        mem["updated"] = time.time()
        self._store[session_id] = mem

    # Optional helpers for metrics/state (thin wrappers around mem dict)
    def get_aims_state(self, session_id: str) -> dict:
        mem = self.get_mem(session_id)
        return mem.get("aims_state") or {}

    def set_aims_state(self, session_id: str, state: dict) -> None:
        if not (self.memory_enabled and session_id):
            return
        mem = self.get_mem(session_id)
        mem["aims_state"] = state
        self.save_mem(session_id, mem)

    def get_aims_metrics(self, session_id: str) -> dict:
        mem = self.get_mem(session_id)
        return mem.get("aims") or {}

    def set_aims_metrics(self, session_id: str, aims: dict) -> None:
        if not (self.memory_enabled and session_id):
            return
        mem = self.get_mem(session_id)
        mem["aims"] = aims
        self.save_mem(session_id, mem)

    # TTL prune (invoked occasionally by API layer)
    def prune_expired(self) -> None:
        if not self.memory_enabled:
            return
        try:
            now = time.time()
            expired = [sid for sid, v in self._store.items() if (now - v.get("updated", now)) > self.memory_ttl_seconds]
            for sid in expired:
                self._store.pop(sid, None)
        except Exception:
            # best-effort only
            pass

    # -------- HTTP cookie helper --------
    def apply_cookie(self, response, session_id: str) -> None:
        """Set the session cookie on a FastAPI Response-like object.

        Behavior-preserving extraction of the repeated set_cookie blocks from app.main.
        Silently ignores errors to match previous try/except.
        """
        try:
            response.set_cookie(
                key=self.cookie.name,
                value=session_id,
                max_age=self.cookie.max_age,
                httponly=True,
                secure=self.cookie.secure,
                samesite=self.cookie.samesite,
                path="/",
            )
        except Exception:
            # Best-effort only; ignore failures
            pass
