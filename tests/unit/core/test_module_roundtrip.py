from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.registry import build_builtin_registry


@pytest.mark.asyncio
async def test_interview_module_round_trip_covers_bootstrap_turn_summary_and_archive():
    settings = SimpleNamespace(
        APP_ENV="local",
        ACTIVE_MODULE="interview",
        module_redis_key_prefix=lambda module_id: f"{module_id}:local:session:",
    )
    registry = build_builtin_registry(settings=settings)
    module = registry.get_active_module(active_module="interview")
    memory_store = {}

    bootstrap = module.initialize_session(
        body=SimpleNamespace(
            sessionId="interview-roundtrip",
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

    assert bootstrap["moduleId"] == "interview"
    assert bootstrap["module"]["state"]["personaName"] == "Hiring Manager"
    assert [artifact["title"] for artifact in bootstrap["module"]["artifacts"]] == [
        "Interview Setup",
        "Response Guidance",
    ]

    turn_result = await module.handle_turn(
        req=object(),
        body=SimpleNamespace(
            message="I led a migration that improved throughput by 25%, and I learned to involve support teams earlier.",
            moduleOptions={"feedbackEnabled": False},
        ),
        ctx=SimpleNamespace(session_id="interview-roundtrip"),
        memory_store=memory_store,
        vertex_config={},
        memory_config={},
        module_runtime_config={},
        logger=MagicMock(),
    )

    response = module.format_module_response(result=turn_result, session_id="interview-roundtrip")
    summary = await module.build_summary(session_id="interview-roundtrip", memory_store=memory_store)
    envelope = module.build_archive_envelope(
        session_id="interview-roundtrip",
        user_id="candidate@example.com",
        data=memory_store["interview-roundtrip"],
        settings=settings,
    )

    assert response["reply"] == "Tell me more about the impact you had and what you learned."
    assert response["artifacts"][0]["kind"] == "interview_prompt"
    assert summary["moduleId"] == "interview"
    assert summary["supported"] is True
    assert summary["signals"]["quantifiedExamples"] == 1
    assert summary["signals"]["reflectionExamples"] == 1
    assert envelope.module_id == "interview"
    assert envelope.archive_schema_version == "interview-v1"
    assert envelope.metadata["moduleId"] == "interview"
    assert envelope.participant_context["personaName"] == "Hiring Manager"
