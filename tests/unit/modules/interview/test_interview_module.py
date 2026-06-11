from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.modules.interview.module import create_interview_training_module


def test_interview_module_manifest_is_distinct_from_aims():
    settings = SimpleNamespace(APP_ENV="local")

    module = create_interview_training_module(settings=settings)
    manifest = module.manifest

    assert manifest.id == "interview"
    assert manifest.display_name == "Interview Practice"
    assert manifest.chat_profile_name == "Interview Coach"
    assert manifest.archive_schema_version == "interview-v1"
    assert manifest.storage_prefix == "interview:local:session:"
    assert manifest.supports_intro is False
    assert manifest.supports_feedback is False
    assert manifest.supports_summary is False
    assert manifest.dialogue_roles.participant_roles == ("candidate", "interviewer")
    assert manifest.dialogue_roles.feedback_roles == ("observer",)
    assert manifest.dialogue_roles.metadata_roles == ("system",)
    assert manifest.dialogue_roles.counted_roles == ("candidate", "interviewer")
    assert manifest.dialogue_roles.user_roles == ("candidate",)
    assert manifest.dialogue_roles.counterpart_roles == ("interviewer",)
    assert manifest.dialogue_roles.display_names["candidate"] == "Candidate"
    assert manifest.frontend_js_bundles == ("/public/js/modules/interview/module-ui.js",)
    assert manifest.branding is not None
    assert manifest.branding.avatar_assets["counterpart"] == "/public/avatars/briefing.svg?v=3"
    assert module.module_id == "interview"
    assert module.display_name == "Interview Practice"
    assert module.storage_prefix() == "interview:local:session:"
    assert module.dialogue_roles() is manifest.dialogue_roles
    assert module.get_ui_manifest() is manifest


def test_interview_module_resume_validation_and_unimplemented_hooks():
    module = create_interview_training_module(settings=SimpleNamespace(APP_ENV="local"))

    mismatch = module.resume_validation(persisted_module_id="aims")
    match = module.resume_validation(persisted_module_id="interview")

    assert mismatch.is_resumable is False
    assert "does not match" in (mismatch.reason or "")
    assert match.is_resumable is True

    for fn in (
        module.build_startup_payload,
        module.build_startup_artifacts,
        module.build_system_instruction,
        module.build_history_projection,
    ):
        with pytest.raises(NotImplementedError):
            fn()


def test_interview_module_initialize_session_serializes_bootstrap_and_persists_module_memory():
    settings = SimpleNamespace(APP_ENV="local")
    module = create_interview_training_module(settings=settings)
    memory_store = {}

    payload = module.initialize_session(
        body=SimpleNamespace(
            sessionId="interview-sid",
            character=None,
            scene=None,
            initialCard=None,
            userInfo={"identifier": "candidate@example.com"},
            connectionId=None,
        ),
        memory_store=memory_store,
        memory_enabled=True,
        logger=MagicMock(),
    )

    assert payload["status"] == "ok"
    assert payload["moduleId"] == "interview"
    assert payload["sessionId"] == "interview-sid"
    assert payload["personaName"] == "Hiring Manager"
    assert payload["transport"]["artifactKind"] == "interview_brief"
    assert "Interview Setup" in payload["initialCard"]
    assert len(payload["module"]["artifacts"]) == 2
    assert payload["module"]["artifacts"][1]["title"] == "Response Guidance"
    assert memory_store["interview-sid"]["module_id"] == "interview"
    assert memory_store["interview-sid"]["history"][0]["role"] == "system"


def test_interview_module_initialize_session_repairs_non_list_history_and_supports_memory_disabled():
    settings = SimpleNamespace(APP_ENV="local")
    module = create_interview_training_module(settings=settings)
    memory_store = {
        "interview-sid": {
            "history": None,
            "full_history": None,
        }
    }

    payload = module.initialize_session(
        body=SimpleNamespace(
            sessionId="interview-sid",
            character="Custom interviewer",
            scene="Custom scene",
            initialCard="Custom card",
            userInfo=None,
            connectionId=None,
        ),
        memory_store=memory_store,
        memory_enabled=True,
        logger=MagicMock(),
    )

    assert payload["character"] == "Custom interviewer"
    assert payload["scene"] == "Custom scene"
    assert memory_store["interview-sid"]["history"][0]["content"] == "Custom card"

    payload_disabled = module.initialize_session(
        body=SimpleNamespace(
            sessionId="disabled-sid",
            character=None,
            scene=None,
            initialCard=None,
            userInfo=None,
            connectionId=None,
        ),
        memory_store={},
        memory_enabled=False,
        logger=MagicMock(),
    )

    assert payload_disabled["moduleId"] == "interview"


@pytest.mark.asyncio
async def test_interview_module_handle_turn_updates_memory_with_non_aims_roles():
    settings = SimpleNamespace(APP_ENV="local")
    module = create_interview_training_module(settings=settings)
    memory_store = {
        "sid": {
            "history": [],
            "full_history": [],
            "module_id": "interview",
            "updated": 0,
        }
    }

    result = await module.handle_turn(
        req=object(),
        body=SimpleNamespace(message="I led the migration project.", coach=False),
        ctx=SimpleNamespace(session_id="sid"),
        memory_store=memory_store,
        vertex_config={},
        memory_config={},
        aims_config={},
        logger=MagicMock(),
    )

    assert result["reply"]
    assert memory_store["sid"]["history"][-2]["role"] == "candidate"
    assert memory_store["sid"]["history"][-1]["role"] == "interviewer"


def test_interview_module_formats_generic_response_without_aims_coaching_shape():
    settings = SimpleNamespace(APP_ENV="local")
    module = create_interview_training_module(settings=settings)

    payload = module.format_module_response(
        result={
            "reply": "Tell me more about how you measured impact.",
            "model": "interview-stub",
            "latency_ms": 5,
            "session": {"mode": "interview"},
        },
        session_id="sid",
    )

    assert payload["reply"] == "Tell me more about how you measured impact."
    assert payload["modelId"] == "interview-stub"
    assert payload["sessionId"] == "sid"
    assert "coaching" not in payload
    assert payload["session"] == {"mode": "interview"}
    assert payload["artifacts"][0]["kind"] == "interview_prompt"


@pytest.mark.asyncio
async def test_interview_module_summary_and_archive_helpers_are_generic():
    settings = SimpleNamespace(APP_ENV="local")
    module = create_interview_training_module(settings=settings)

    summary = await module.build_summary()
    archive = module.build_archive_payload()
    envelope = module.build_archive_envelope(
        session_id="sid",
        user_id="candidate@example.com",
        data={"history": [{"role": "candidate", "content": "hello"}]},
        settings=settings,
    )

    assert summary == {"moduleId": "interview", "supported": False}
    assert archive is None
    assert envelope.module_id == "interview"
    assert envelope.metadata["moduleId"] == "interview"
    assert envelope.transcript == ({"role": "candidate", "content": "hello"},)
    assert module.build_jailbreak_fallback() == "Let's stay focused on the interview scenario."
