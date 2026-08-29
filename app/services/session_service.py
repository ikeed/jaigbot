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
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from app.chat_roles import ROLE_USER, ROLE_ASSISTANT

logger = logging.getLogger(__name__)

# Single-flight guard for prune_expired. It runs in a worker thread now rather than on the
# event loop, so two overlapping requests could otherwise prune concurrently and race each
# other's read-modify-write of the GCS persona index. Module-level because SessionService
# is constructed per request.
_PRUNE_LOCK = threading.Lock()


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
    def trim_history(history: list, max_turns: int) -> list:
        """Trim history to the last *max_turns* dialogue pairs.

        Coach entries are interleaved but should not count toward the
        turn budget.  We keep the last N user+assistant messages (where
        N = max_turns * 2) plus any coach messages that fall within
        that window.
        """
        # Count only dialogue (non-coach) entries
        dialogue_count = sum(1 for m in history if m.get("role") in (ROLE_USER, ROLE_ASSISTANT))
        max_dialogue = max_turns * 2
        if dialogue_count <= max_dialogue:
            return history

        # Walk backwards keeping last max_dialogue dialogue entries
        # plus any coach entries that appear between them.
        kept: list = []
        seen_dialogue = 0
        for entry in reversed(history):
            if entry.get("role") in (ROLE_USER, ROLE_ASSISTANT):
                if seen_dialogue >= max_dialogue:
                    break
                seen_dialogue += 1
            kept.append(entry)
        kept.reverse()
        return kept

    # TTL prune. Queued onto the request's BackgroundTasks by ChatOrchestrator and run in
    # Starlette's worker threadpool after the response has been sent.
    def prune_expired(self) -> None:
        if not self.memory_enabled:
            return
        if not _PRUNE_LOCK.acquire(blocking=False):
            logger.debug("prune_expired already running; skipping this turn")
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
                    # This is the one place a session's final state gets decided:
                    # it went stale without ever reaching game_over or a report,
                    # so it's genuinely abandoned rather than still in progress.
                    if not archive_data.get("game_over") and "error_report" not in archive_data:
                        archive_data["exit_context"] = "abandoned"
                    try:
                        # This upload is synchronous, but prune_expired now runs in a
                        # background worker thread after the response, so it no longer
                        # blocks a user's turn.
                        # finalize_persona_index=True: prune_expired is the single point that
                        # settles a session's outcome (completed, abandoned, or reported), so
                        # this is where the "open" persona-index row gets its final outcome.
                        storage_service.upload_session(sid, user_id, archive_data, finalize_persona_index=True)
                    except Exception as e:
                        logger.debug("Failed to archive session %s during prune: %s", sid, e)
                        
                self._store.pop(sid, None)
        except Exception as e:
            # best-effort only
            logger.debug("Error during prune_expired: %s", e)
        finally:
            _PRUNE_LOCK.release()

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
