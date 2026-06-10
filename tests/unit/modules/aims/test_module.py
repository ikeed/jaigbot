from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.modules.aims.module import create_aims_training_module


def test_aims_module_manifest_exposes_expected_phase1_metadata():
    settings = SimpleNamespace(redis_key_prefix="aims:prod:session:")

    module = create_aims_training_module(settings=settings)
    manifest = module.manifest

    assert manifest.id == "aims"
    assert manifest.display_name == "AIMS"
    assert manifest.chat_profile_name == "AIMSBot"
    assert manifest.storage_prefix == "aims:prod:session:"
    assert manifest.archive_schema_version == "aims-v1"
    assert manifest.supports_intro is True
    assert manifest.supports_feedback is True
    assert manifest.supports_summary is True
    assert manifest.dialogue_roles.participant_roles == ("user", "assistant")
    assert manifest.dialogue_roles.feedback_roles == ("coach",)
    assert manifest.dialogue_roles.metadata_roles == ("system",)
    assert manifest.dialogue_roles.counted_roles == ("user", "assistant")
    assert module.module_id == "aims"
    assert module.display_name == "AIMS"
    assert module.storage_prefix() == "aims:prod:session:"
    assert module.get_ui_manifest() is manifest


def test_aims_module_resume_validation_rejects_module_mismatch():
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)

    mismatch = module.resume_validation(persisted_module_id="interview")
    match = module.resume_validation(persisted_module_id="aims")

    assert mismatch.is_resumable is False
    assert "does not match" in (mismatch.reason or "")
    assert match.is_resumable is True


def test_aims_module_future_hooks_remain_explicitly_unimplemented():
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)

    for fn in (
        module.initialize_session,
        module.build_startup_payload,
        module.build_startup_artifacts,
        module.build_system_instruction,
        module.build_history_projection,
        module.build_summary,
        module.build_jailbreak_fallback,
    ):
        try:
            fn()
        except NotImplementedError:
            continue
        raise AssertionError(f"{fn.__name__} should raise NotImplementedError in Phase 2")


def test_aims_module_formats_generic_result_into_compatibility_payload():
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)

    payload = module.format_module_response(
        result={
            "reply": "Patient reply",
            "model": "gemini-test",
            "latency_ms": 42,
            "coaching": {"step": "Announce"},
            "session": {"totalTurns": 1},
            "coach_post": {"title": "Done", "lines": ["Good job"]},
        },
        session_id="sid-1",
    )

    assert payload["reply"] == "Patient reply"
    assert payload["text"] == "Patient reply"
    assert payload["model"] == "gemini-test"
    assert payload["modelId"] == "gemini-test"
    assert payload["latencyMs"] == 42
    assert payload["latency_ms"] == 42
    assert payload["sessionId"] == "sid-1"
    assert payload["coaching"] == {"step": "Announce"}
    assert payload["session"] == {"totalTurns": 1}
    assert payload["coachPost"] == {"title": "Done", "lines": ["Good job"]}
    assert payload["gameOver"] is True
    assert payload["completion"]["kind"] == "game_over"


@pytest.mark.asyncio
async def test_aims_module_handle_turn_routes_to_coaching_when_enabled(monkeypatch):
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)

    class FakeAimsHandler:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        @staticmethod
        async def handle(req, body, ctx):
            return {"reply": "patient", "model": "m", "latency_ms": 1}

    monkeypatch.setattr("app.services.aims_coaching_handler.AimsCoachingHandler", FakeAimsHandler)

    result = await module.handle_turn(
        req=object(),
        body=SimpleNamespace(coach=True),
        ctx=object(),
        memory_store={},
        vertex_config={"model_id": "m"},
        memory_config={"enabled": True, "max_turns": 8},
        aims_config={"enabled": True, "force_default": False},
        logger=MagicMock(),
    )

    assert result["reply"] == "patient"
    assert result["_dispatch_path"] == "coaching"


@pytest.mark.asyncio
async def test_aims_module_handle_turn_routes_to_legacy_when_coaching_not_selected(monkeypatch):
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)

    class FakeLegacyHandler:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        @staticmethod
        async def handle(req, body, ctx):
            return {"reply": "legacy", "model": "m", "latency_ms": 1}

    monkeypatch.setattr("app.services.legacy_chat_handler.LegacyChatHandler", FakeLegacyHandler)

    result = await module.handle_turn(
        req=object(),
        body=SimpleNamespace(coach=False),
        ctx=object(),
        memory_store={},
        vertex_config={"model_id": "m"},
        memory_config={"enabled": True, "max_turns": 8},
        aims_config={"enabled": False, "force_default": False},
        logger=MagicMock(),
    )

    assert result["reply"] == "legacy"
    assert result["_dispatch_path"] == "legacy"


def test_aims_module_build_archive_payload_returns_endgame_archive_and_updates_memory():
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)
    memory_store = {}
    session_service = MagicMock()
    session_service.get_mem.return_value = {"history": [{"role": "user", "content": "hi"}]}
    ctx = SimpleNamespace(session_id="sid", user_info={"identifier": "doctor@example.com"})

    archive = module.build_archive_payload(
        result={"coach_post": {"title": "Done"}},
        ctx=ctx,
        session_service=session_service,
        memory_store=memory_store,
    )

    assert archive is not None
    assert archive["session_id"] == "sid"
    assert archive["user_id"] == "doctor@example.com"
    assert archive["game_over"] is True
    assert archive["coach_post"] == {"title": "Done"}
    assert archive["exported_via"] == "endgame"
    assert memory_store["sid"]["session_ended"] > 0


def test_aims_module_build_archive_payload_returns_none_without_endgame():
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)

    archive = module.build_archive_payload(
        result={"reply": "still going"},
        ctx=SimpleNamespace(session_id="sid", user_info=None),
        session_service=MagicMock(),
        memory_store={},
    )

    assert archive is None
