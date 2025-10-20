from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any, Tuple
import time

from app.persona import DEFAULT_CHARACTER, DEFAULT_SCENE
from app.services.session_service import SessionService
from app.services.chat_helpers import build_system_instruction, format_history


@dataclass(frozen=True)
class ChatContext:
    session_id: str
    generated_session: bool
    mem: dict
    effective_character: Optional[str]
    effective_scene: Optional[str]
    system_instruction: Optional[str]
    history_text: str
    parent_last: str


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
        do_prune_mod: int = 29,
    ) -> None:
        self.sess = session_service
        self.memory_enabled = memory_enabled
        self.memory_max_turns = int(memory_max_turns)
        self.memory_ttl_seconds = int(memory_ttl_seconds)
        self._do_prune_mod = int(do_prune_mod)

    def build(self, req: Any, body_session_id: Optional[str], character: Optional[str], scene: Optional[str]) -> ChatContext:
        # occasional prune (same modulo behavior)
        now = time.time()
        if int(now) % self._do_prune_mod == 0:
            self.sess.prune_expired()

        # resolve session
        session_id, generated_session = self.sess.ensure_session(req, body_session_id)

        mem: dict = {}
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

        # last assistant turn (parent voice)
        parent_last = ""
        if mem and mem.get("history"):
            for t in reversed(mem["history"]):
                if t.get("role") == "assistant":
                    parent_last = t.get("content") or ""
                    break

        # compact history text like before (tail of last N turns)
        history_text = format_history(mem.get("history", []), self.memory_max_turns) if mem else ""

        return ChatContext(
            session_id=session_id,
            generated_session=generated_session,
            mem=mem,
            effective_character=effective_character,
            effective_scene=effective_scene,
            system_instruction=system_instruction,
            history_text=history_text,
            parent_last=parent_last,
        )
