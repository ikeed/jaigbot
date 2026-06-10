from app.services.chat_context import ChatContextBuilder


class FakeSessionService:
    def __init__(self):
        self._mem = {}
        self._last_ensured = None

    def prune_expired(self):
        # No-op for tests
        pass

    def ensure_session(self, req, body_session_id, user_info=None):
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
    assert "Doctor: hi" in ht
    assert "Assistant: hello" in ht
    assert "Doctor: how are you?" in ht

    # person_last should be the last assistant message from memory
    assert ctx.person_last == "hello"


def test_chat_context_builder_uses_module_counted_roles_for_history_tail():
    sess = FakeSessionService()
    builder = ChatContextBuilder(
        session_service=sess,
        memory_enabled=True,
        memory_max_turns=1,
        memory_ttl_seconds=3600,
        counted_roles=("student", "interviewer"),
    )

    sid, _ = sess.ensure_session(None, None)
    mem = sess.get_mem(sid)
    mem["history"] = [
        {"role": "system", "content": "meta"},
        {"role": "mentor", "content": "coach"},
        {"role": "student", "content": "Q1"},
        {"role": "interviewer", "content": "A1"},
        {"role": "mentor", "content": "coach-2"},
        {"role": "student", "content": "Q2"},
        {"role": "interviewer", "content": "A2"},
    ]

    ctx = builder.build(req=None, body_session_id=sid, character="CHAR", scene="SCENE")

    assert ctx.history_text.split("\n") == ["Assistant: coach-2", "Assistant: Q2", "Assistant: A2"]


def test_chat_context_builder_uses_module_counterpart_roles_and_labels():
    sess = FakeSessionService()
    builder = ChatContextBuilder(
        session_service=sess,
        memory_enabled=True,
        memory_max_turns=2,
        memory_ttl_seconds=3600,
        counted_roles=("candidate", "interviewer"),
        counterpart_roles=("interviewer",),
        role_labels={"candidate": "Candidate", "interviewer": "Interviewer"},
    )

    sid, _ = sess.ensure_session(None, None)
    mem = sess.get_mem(sid)
    mem["history"] = [
        {"role": "candidate", "content": "I led the migration."},
        {"role": "interviewer", "content": "What tradeoffs did you make?"},
    ]

    ctx = builder.build(req=None, body_session_id=sid, character="CHAR", scene="SCENE")

    assert ctx.person_last == "What tradeoffs did you make?"
    assert ctx.history_text.split("\n") == [
        "Candidate: I led the migration.",
        "Interviewer: What tradeoffs did you make?",
    ]
