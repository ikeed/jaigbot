from dataclasses import dataclass

from app.services.chat_context import ChatContextBuilder


class FakeSessionService:
    def __init__(self):
        self._mem = {}
        self._last_ensured = None

    def prune_expired(self):
        # No-op for tests
        pass

    def ensure_session(self, req, body_session_id):
        sid = body_session_id or "test-sid"
        self._last_ensured = sid
        self._mem.setdefault(sid, {
            "history": [],
            "character": None,
            "scene": None,
        })
        return sid, (body_session_id is None)

    def update_persona_scene(self, session_id, character, scene):
        m = self._mem.setdefault(session_id, {"history": []})
        if character is not None:
            m["character"] = character
        if scene is not None:
            m["scene"] = scene
        return m

    def get_mem(self, session_id):
        return self._mem.get(session_id)


def test_chat_context_builder_composes_instruction_and_history():
    sess = FakeSessionService()
    b = ChatContextBuilder(
        session_service=sess,
        memory_enabled=True,
        memory_max_turns=3,
        memory_ttl_seconds=3600,
    )

    # Seed memory with a couple of turns
    sid, _ = sess.ensure_session(None, None)
    m = sess.get_mem(sid)
    m["history"] = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "how are you?"},
    ]

    # Provide persona/scene overrides
    ctx = b.build(req=None, body_session_id=sid, character="CHAR", scene="SCENE")

    # System instruction includes both persona and scene
    assert ctx.system_instruction is not None
    si = ctx.system_instruction
    assert "You are roleplaying as: CHAR" in si
    assert "Scene objectives/context: SCENE" in si

    # History text includes recent turns labeled correctly
    ht = ctx.history_text
    assert "User: hi" in ht
    assert "Assistant: hello" in ht
    assert "User: how are you?" in ht

    # parent_last should be the last assistant message from memory
    assert ctx.parent_last == "hello"
