from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Any, Mapping, Sequence

from app.chat_roles import ROLE_ASSISTANT
from app.persona import DEFAULT_CHARACTER, DEFAULT_SCENE
from app.services.chat_helpers import build_system_instruction, format_history
from app.services.session_service import SessionService


@dataclass(frozen=True)
class ChatContext:
    session_id: str
    generated_session: bool
    mem: dict
    effective_character: Optional[str]
    effective_scene: Optional[str]
    system_instruction: Optional[str]
    history_text: str
    person_last: str
    user_info: Optional[dict] = None


class ChatContextBuilder:
    """Builds a request-scoped chat context.

    Encapsulates the previously inlined logic in app.main:
    - optional TTL prune
    - ensure session id
    - update persona/scene and fetch memory
    - compute effective persona/scene
    - build system instruction
    - derive compact history_text and last parent (assistant) turn

    Behavior-preserving and test-friendly.
    """

    def __init__(
        self,
        *,
        session_service: SessionService,
        memory_enabled: bool,
        memory_max_turns: int,
        memory_ttl_seconds: int,
        counted_roles: tuple[str, ...] | None = None,
        counterpart_roles: Sequence[str] | None = None,
        role_labels: Mapping[str, str] | None = None,
        do_prune_mod: int = 29,
    ) -> None:
        self.sess = session_service
        self.memory_enabled = memory_enabled
        self.memory_max_turns = int(memory_max_turns)
        self.memory_ttl_seconds = int(memory_ttl_seconds)
        self.counted_roles = counted_roles or ("user", "assistant")
        self.counterpart_roles = tuple(
            str(role).strip().lower() for role in (counterpart_roles or (ROLE_ASSISTANT,)) if str(role).strip()
        )
        self.role_labels = dict(role_labels or {})
        self._do_prune_mod = int(do_prune_mod)

    def build(self, req: Any, body_session_id: Optional[str], character: Optional[str], scene: Optional[str], user_info: Optional[dict] = None) -> ChatContext:
        # occasional prune (same modulo behavior)
        now = time.time()
        if int(now) % self._do_prune_mod == 0:
            self.sess.prune_expired()

        # resolve session
        session_id, generated_session = self.sess.ensure_session(req, body_session_id, user_info)

        if self.memory_enabled and session_id:
            # update persona/scene first (like main.py), then fetch mem
            mem = self.sess.update_persona_scene(session_id, character, scene) or self.sess.get_mem(session_id)
        else:
            mem = {}

        # compute effective persona/scene with defaults
        effective_character = (
            (mem.get("character") if mem else None)
            or (character or None)
            or (DEFAULT_CHARACTER or None)
        )
        effective_scene = (
            (mem.get("scene") if mem else None)
            or (scene or None)
            or (DEFAULT_SCENE or None)
        )

        system_instruction = build_system_instruction(effective_character, effective_scene)

        # last counterpart turn (person/interviewer/etc voice)
        person_last = ""
        if mem and mem.get("history"):
            for t in reversed(mem["history"]):
                if str(t.get("role") or "").strip().lower() in self.counterpart_roles:
                    person_last = t.get("content") or ""
                    break

        # compact history text like before (tail of last N turns)
        history_text = (
            format_history(
                mem.get("history", []),
                self.memory_max_turns,
                counted_roles=self.counted_roles,
                role_labels=self.role_labels,
            )
            if mem
            else ""
        )

        # identify effective user_info (session vs request)
        effective_user_info = (mem.get("user_info") if mem else None) or user_info

        return ChatContext(
            session_id=session_id,
            generated_session=generated_session,
            mem=mem,
            effective_character=effective_character,
            effective_scene=effective_scene,
            system_instruction=system_instruction,
            history_text=history_text,
            person_last=person_last,
            user_info=effective_user_info,
        )
