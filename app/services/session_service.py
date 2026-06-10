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

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from app.chat_roles import ROLE_USER, ROLE_ASSISTANT

logger = logging.getLogger(__name__)


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
        module_id: str | None = None,
        counted_roles: tuple[str, ...] | None = None,
    ) -> None:
        self._store = store
        self.cookie = cookie
        self.memory_enabled = memory_enabled
        self.memory_max_turns = int(memory_max_turns)
        self.memory_ttl_seconds = int(memory_ttl_seconds)
        self.module_id = module_id
        self.counted_roles = counted_roles or (ROLE_USER, ROLE_ASSISTANT)

    # -------- Session ID handling --------
    def ensure_session(self, request, body_session_id: Optional[str], user_info: Optional[dict] = None) -> Tuple[str, bool]:
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
                mem = {
                    "history": [],
                    "full_history": [],
                    "character": None,
                    "scene": None,
                    "module_id": self.module_id,
                    "updated": now,
                    "session_started": now,
                    "user_info": user_info,
                }
                self._store[sid] = mem
            else:
                # touch updated lazily; callers also update as needed
                mem.setdefault("updated", now)
                mem.setdefault("full_history", [])
                mem.setdefault("session_started", now)
                if self.module_id and not mem.get("module_id"):
                    mem["module_id"] = self.module_id
                if user_info and not mem.get("user_info"):
                    mem["user_info"] = user_info
                self._store[sid] = mem
        return sid, generated

    # -------- Memory helpers --------
    def get_mem(self, session_id: str) -> dict:
        if not (self.memory_enabled and session_id):
            return {}
        return self._store.get(session_id) or {}

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

    @staticmethod
    def trim_history(history: list, max_turns: int, counted_roles: tuple[str, ...] | None = None) -> list:
        """Trim history to the last *max_turns* dialogue pairs.

        Coach entries are interleaved but should not count toward the
        turn budget.  We keep the last N user+assistant messages (where
        N = max_turns * 2) plus any coach messages that fall within
        that window.
        """
        # Count only dialogue (non-coach) entries
        countable_roles = counted_roles or (ROLE_USER, ROLE_ASSISTANT)
        dialogue_count = sum(1 for m in history if m.get("role") in countable_roles)
        max_dialogue = max_turns * 2
        if dialogue_count <= max_dialogue:
            return history

        # Walk backwards keeping last max_dialogue dialogue entries
        # plus any coach entries that appear between them.
        kept: list = []
        seen_dialogue = 0
        for entry in reversed(history):
            if entry.get("role") in countable_roles:
                if seen_dialogue >= max_dialogue:
                    break
                seen_dialogue += 1
            kept.append(entry)
        kept.reverse()
        return kept

    # TTL prune (invoked occasionally by API layer)
    def prune_expired(self) -> None:
        if not self.memory_enabled:
            return
        try:
            from app.services.storage_service import storage_service
            now = time.time()
            expired = [
                sid
                for sid, v in self._store.items()
                if isinstance(v, dict)
                and ("history" in v or "full_history" in v)
                and (now - v.get("updated", now)) > self.memory_ttl_seconds
            ]
            for sid in expired:
                mem = self._store.get(sid)
                if mem:
                    # Archive to GCS before popping from store
                    user_info = mem.get("user_info")
                    user_id = user_info.get("identifier") if user_info else "anonymous"
                    
                    # Only archive if it hasn't been explicitly exported yet (best-effort flag)
                    # We can use a flag in the session data to avoid double-archiving if desired,
                    # but GCS overwrite is also fine.
                    archive_data = {
                        **mem,
                        "session_id": sid,
                        "user_id": user_id,
                        "exported_via": "prune_expired",
                        "pruned_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))
                    }
                    try:
                        # Note: prune_expired is usually called in the background or between requests,
                        # so we call upload_session directly (blocking this minor loop, not the user).
                        storage_service.upload_session(sid, user_id, archive_data)
                    except Exception as e:
                        logger.debug("Failed to archive session %s during prune: %s", sid, e)
                        
                self._store.pop(sid, None)
        except Exception as e:
            # best-effort only
            logger.debug("Error during prune_expired: %s", e)

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
        except Exception as e:
            # Best-effort only; ignore failures
            logger.debug("Failed to apply session cookie: %s", e)
