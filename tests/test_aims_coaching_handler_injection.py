import logging
from unittest.mock import AsyncMock, Mock

import pytest

from app.models import ClassifierResult, Coaching
from app.services.aims_coaching_handler import AimsCoachingHandler
from app.services.chat_context import ChatContext


def _handler(*, classifier, patient_reply, metrics, feedback):
    return AimsCoachingHandler(
        memory_store={},
        vertex_config={
            "project_id": "proj",
            "region": "us-central1",
            "vertex_location": "us-central1",
            "model_id": "model",
            "model_fallbacks": [],
            "temperature": 0.0,
            "max_tokens": 256,
            "client_cls": None,
        },
        memory_config={"enabled": True, "max_turns": 10},
        logger=logging.getLogger("test"),
        classifier_service=classifier,
        patient_reply_service=patient_reply,
        metrics_service=metrics,
        coach_feedback_history_service=feedback,
    )


@pytest.mark.asyncio
async def test_handle_uses_injected_services(monkeypatch):
    classify_result = ClassifierResult(
        is_small_talk=False,
        is_vaccine_relevant=True,
        aims=Coaching(
            step="Announce",
            steps=["Announce"],
            score=2,
            reasons=["Clear recommendation."],
            tips=["Ask what questions they have."],
        ),
        safety_flags=[],
        person_topic=None,
        reasoning="test",
    )
    classifier = Mock()
    classifier.classify_turn = AsyncMock(return_value=classify_result)

    patient_reply = Mock()
    patient_reply.generate = AsyncMock(return_value={"patient_reply": "Thanks, Doctor."})

    metrics = Mock()

    def persist_metrics(mem, cls_payload):
        mem["metrics_persisted"] = True

    metrics.persist.side_effect = persist_metrics
    metrics.build_summary.return_value = {
        "totalTurns": 1,
        "perStepCounts": {"Announce": 1},
        "runningAverage": {"Announce": 2.0},
    }

    feedback = Mock()
    feedback.filter_user_facing_reasons.side_effect = (
        lambda reasons, step=None: [
            reason for reason in reasons if not reason.lower().startswith("internal")
        ]
    )

    def append_feedback(**kwargs):
        kwargs["mem"]["coach_feedback_appended"] = True

    feedback.append.side_effect = append_feedback
    handler = _handler(
        classifier=classifier,
        patient_reply=patient_reply,
        metrics=metrics,
        feedback=feedback,
    )

    async def fake_mapping():
        return {}

    async def fake_endgame(mem, reply_payload, session_obj, session_id):
        return None

    monkeypatch.setattr(handler, "_load_aims_mapping", fake_mapping)
    monkeypatch.setattr(handler, "_check_end_game", fake_endgame)

    ctx = ChatContext(
        session_id="sid",
        generated_session=False,
        mem={"history": [], "full_history": []},
        effective_character="Persona text",
        effective_scene="Scene text",
        system_instruction=None,
        history_text="Clinician: hello",
        person_last="",
        user_info={"identifier": "clinician@example.com", "metadata": {"name": "Craig Burnett"}},
    )

    from app.models import ChatRequest

    result = await handler.handle(
        req=None,
        body=ChatRequest(message="I recommend the vaccine today.", sessionId="sid", coach=True),
        ctx=ctx,
    )

    assert result["reply"] == "Thanks, Doctor."
    assert result["coaching"]["step"] == "Announce"
    assert result["session"]["perStepCounts"]["Announce"] == 1

    classifier.classify_turn.assert_awaited_once()
    classify_call = classifier.classify_turn.await_args.kwargs
    assert classify_call["clinician_message"] == "I recommend the vaccine today."

    patient_reply.generate.assert_awaited_once()
    reply_call = patient_reply.generate.await_args.kwargs
    assert reply_call["clinician_name"] == "Dr. Burnett"
    assert reply_call["character"] == "Persona text"

    metrics.persist.assert_called_once()
    metrics.build_summary.assert_called_once()

    feedback.append.assert_called_once()
    feedback_call = feedback.append.call_args.kwargs
    assert feedback_call["session_id"] == "sid"
    assert feedback_call["reply_payload"] == {"patient_reply": "Thanks, Doctor."}
