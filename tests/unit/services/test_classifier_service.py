import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models import ClassifierResult
from app.services.classifier_service import ClassifierService


@pytest.fixture
def mock_gemini_client():
    client = MagicMock()
    client.generate_text_async = AsyncMock()
    return client

@pytest.fixture
def classifier_service(mock_gemini_client):
    service = ClassifierService(
        project_id="test-project",
        location="us-central1",
        model_id="gemini-pro",
        client_cls=lambda **kwargs: mock_gemini_client
    )
    return service

@pytest.mark.asyncio
async def test_classify_turn_success(classifier_service, mock_gemini_client):
    # Mock successful JSON response from Gemini
    mock_response = {
        "is_small_talk": False,
        "is_vaccine_relevant": True,
        "aims": {
            "step": "Mirror",
            "score": 3,
            "reasons": ["Mirrored concern well"],
            "tips": ["Good job"]
        },
        "safety_flags": [],
        "reasoning": "Test reasoning"
    }
    mock_gemini_client.generate_text_async.return_value = json.dumps(mock_response)

    result = await classifier_service.classify_turn(clinician_message="I hear you're worried about side effects.",
                                                    person_last="I'm scared of the shots.", history=[],
                                                    prior_announced=False, prior_phase="PreAnnounce", mapping={})

    assert isinstance(result, ClassifierResult)
    assert result.is_small_talk is False
    assert result.aims.step == "Mirror"
    assert result.aims.score == 3
    assert "Mirrored concern well" in result.aims.reasons
    assert "observations" not in result.aims.model_dump()
    assert "feedback_items" not in result.aims.model_dump()
    assert "person_events" not in result.model_dump()
    assert "resolution" not in result.model_dump()


@pytest.mark.asyncio
async def test_classify_turn_preserves_optional_semantic_contract_fields(
    classifier_service, mock_gemini_client
):
    mock_response = {
        "is_small_talk": False,
        "is_vaccine_relevant": True,
        "aims": {
            "step": "Mirror",
            "score": 3,
            "reasons": ["Mirrored concern well"],
            "tips": [],
            "observations": {
                "reflection_present": True,
                "accuracy_check_present": False,
                "question_count": 1,
            },
            "feedback_items": [
                {
                    "step": "Mirror",
                    "tone": "praise",
                    "code": "mirror_reflection",
                    "text": "You mirrored the side-effect concern clearly.",
                    "evidence_spans": ["worried about side effects"],
                    "target_observation": "reflection_present",
                }
            ],
        },
        "person_events": [
            {
                "event_type": "concern_raised",
                "topic": "side_effects",
                "evidence_spans": ["scared of the shots causing a fever"],
                "confidence": "high",
            }
        ],
        "resolution": {
            "is_endgame": False,
            "remaining_active_concern": True,
            "evidence_spans": ["I'm scared of the shots causing a fever."],
        },
        "safety_flags": [],
        "person_topic": "side_effects",
        "reasoning": "Optional semantic fields are present.",
    }
    mock_gemini_client.generate_text_async.return_value = json.dumps(mock_response)

    result = await classifier_service.classify_turn(
        clinician_message="It sounds like you're worried about side effects.",
        person_last="I'm scared of the shots causing a fever.",
        history=[],
        prior_announced=True,
        prior_phase="InquireMirror",
        mapping={},
    )

    assert result.aims.observations is not None
    assert result.aims.observations.reflection_present is True
    assert result.aims.observations.accuracy_check_present is False
    assert result.aims.observations.question_count == 1
    assert result.aims.feedback_items[0].code == "mirror_reflection"
    assert result.aims.feedback_items[0].text == "You mirrored the side-effect concern clearly."
    assert result.aims.feedback_items[0].evidence_spans == ["worried about side effects"]
    assert result.person_events[0].event_type == "concern_raised"
    assert result.person_events[0].topic == "side_effects"
    assert result.resolution is not None
    assert result.resolution.is_endgame is False
    assert result.resolution.remaining_active_concern is True


@pytest.mark.asyncio
async def test_classify_turn_ignores_malformed_optional_semantic_fields(
    classifier_service, mock_gemini_client
):
    mock_response = {
        "is_small_talk": False,
        "is_vaccine_relevant": True,
        "aims": {
            "step": "Inquire",
            "score": 2,
            "reasons": ["Asked about concerns"],
            "tips": [],
            "observations": {"question_count": "not-a-number"},
            "feedback_items": [
                {"text": ""},
                {"text": "Ask one open concern question.", "evidence_spans": ["What worries you?"]},
            ],
        },
        "person_events": [{"topic": "trust"}, "bad event"],
        "resolution": ["bad resolution"],
        "safety_flags": [],
        "person_topic": "trust",
    }
    mock_gemini_client.generate_text_async.return_value = json.dumps(mock_response)

    result = await classifier_service.classify_turn(
        clinician_message="What worries you most about vaccines?",
        person_last="I do not really trust the process.",
        history=[],
        prior_announced=True,
        prior_phase="InquireMirror",
        mapping={},
    )

    assert result.aims.step == "Inquire"
    assert result.aims.observations is None
    assert len(result.aims.feedback_items) == 1
    assert result.aims.feedback_items[0].text == "Ask one open concern question."
    assert result.person_events == []
    assert result.resolution is None


@pytest.mark.asyncio
async def test_classify_turn_prompt_includes_recent_context_and_concern_lists(
    classifier_service, mock_gemini_client
):
    mock_gemini_client.generate_text_async.return_value = json.dumps(
        {
            "is_small_talk": False,
            "is_vaccine_relevant": True,
            "aims": {"step": "Inquire", "score": 2, "reasons": [], "tips": []},
            "safety_flags": [],
            "reasoning": "ok",
        }
    )

    history = [
        {"role": "user", "content": "We recommend the MMR vaccine today."},
        {"role": "assistant", "content": "I thought measles was basically gone."},
    ]
    await classifier_service.classify_turn(
        clinician_message="What concerns do you have about the MMR vaccine?",
        person_last="I thought measles was basically gone.",
        history=history,
        prior_announced=True,
        prior_phase="InquireMirror",
        mapping={},
        inquired_concerns_list=["disease_risk", "trust"],
        mirrored_concerns_list=["trust"],
    )

    prompt = mock_gemini_client.generate_text_async.await_args.args[0]
    system_instruction = mock_gemini_client.generate_text_async.await_args.kwargs["system_instruction"]
    assert "Doctor: We recommend the MMR vaccine today." in prompt
    assert "Assistant: I thought measles was basically gone." in prompt
    assert "Inquired Concerns: disease_risk, trust" in prompt
    assert "Mirrored Concerns: trust" in prompt
    assert "Phase: InquireMirror" in prompt
    assert "Triple-Move" in system_instruction
    assert (
        mock_gemini_client.generate_text_async.await_args.kwargs["response_mime_type"]
        == "application/json"
    )
    assert mock_gemini_client.generate_text_async.await_args.kwargs["thinking_budget"] is None
    assert mock_gemini_client.generate_text_async.await_args.kwargs["thinking_level"] == "minimal"

@pytest.mark.asyncio
async def test_classify_turn_with_person_topic(classifier_service, mock_gemini_client):
    # Mock successful JSON response with person_topic
    mock_response = {
        "is_small_talk": False,
        "is_vaccine_relevant": True,
        "person_topic": "side_effects",
        "aims": {
            "step": "Mirror",
            "score": 3,
            "reasons": ["Mirrored concern well"],
            "tips": ["Good job"]
        },
        "safety_flags": [],
        "reasoning": "Person mentioned side effects."
    }
    mock_gemini_client.generate_text_async.return_value = json.dumps(mock_response)

    result = await classifier_service.classify_turn(clinician_message="I hear you're worried about side effects.",
                                                    person_last="I'm scared of the shots causing a fever.", history=[],
                                                    prior_announced=False, prior_phase="PreAnnounce", mapping={})

    assert result.person_topic == "side_effects"

@pytest.mark.asyncio
async def test_classify_turn_returns_unavailable_when_llm_classification_fails_by_default(
    classifier_service, mock_gemini_client
):
    # Mock error from Gemini
    mock_gemini_client.generate_text_async.side_effect = Exception("Gemini down")

    result = await classifier_service.classify_turn(clinician_message="I recommend the MMR today.", person_last="Okay.",
                                                    history=[], prior_announced=False, prior_phase="PreAnnounce",
                                                    mapping={})

    assert isinstance(result, ClassifierResult)
    assert result.aims.step is None
    assert result.aims.score == 0
    assert result.aims.feedback_items[0].code == "classification_unavailable"


@pytest.mark.asyncio
async def test_classify_turn_can_enable_deterministic_fallback(mock_gemini_client):
    service = ClassifierService(
        project_id="test-project",
        location="us-central1",
        model_id="gemini-pro",
        client_cls=lambda **kwargs: mock_gemini_client,
        heuristic_fallback_enabled=True,
    )
    mock_gemini_client.generate_text_async.side_effect = Exception("Gemini down")

    result = await service.classify_turn(
        clinician_message="I recommend the MMR today.",
        person_last="Okay.",
        history=[],
        prior_announced=False,
        prior_phase="PreAnnounce",
        mapping={},
    )

    assert result.aims.step == "Announce"
    assert "fallback" in result.aims.reasons


@pytest.mark.asyncio
async def test_classify_turn_can_disable_deterministic_fallback(mock_gemini_client):
    service = ClassifierService(
        project_id="test-project",
        location="us-central1",
        model_id="gemini-pro",
        client_cls=lambda **kwargs: mock_gemini_client,
        heuristic_fallback_enabled=False,
    )
    mock_gemini_client.generate_text_async.side_effect = Exception("Gemini down")

    with patch("app.aims_engine.evaluate_turn") as evaluate_turn:
        result = await service.classify_turn(
            clinician_message="I recommend the MMR today.",
            person_last="Okay.",
            history=[],
            prior_announced=False,
            prior_phase="PreAnnounce",
            mapping={},
        )

    evaluate_turn.assert_not_called()
    assert isinstance(result, ClassifierResult)
    assert result.aims.step is None
    assert result.aims.score == 0
    assert result.aims.reasons == ["AIMS coaching is temporarily unavailable for this turn."]
    assert result.aims.feedback_items[0].code == "classification_unavailable"
    assert result.reasoning == "classification unavailable"

@pytest.mark.asyncio
async def test_triple_move_detection(classifier_service, mock_gemini_client):
    # Mock successful JSON response with multiple steps (Mirror+Secure+Inquire)
    mock_response = {
        "is_small_talk": False,
        "is_vaccine_relevant": True,
        "aims": {
            "steps": ["Mirror", "Secure", "Inquire"],
            "score": 3,
            "reasons": ["Validated, educated, and surfaced next concern."],
            "tips": ["Excellent synthesis"]
        },
        "safety_flags": [],
        "reasoning": "Triple-move detected."
    }
    mock_gemini_client.generate_text_async.return_value = json.dumps(mock_response)

    result = await classifier_service.classify_turn(
        clinician_message="I hear you're worried about side effects, and actually the data shows they are quite rare. What else is on your mind?",
        person_last="I'm scared of side effects.", history=[], prior_announced=True, prior_phase="InquireMirror",
        mapping={})

    assert result.aims.step == "Mirror+Secure+Inquire"
    assert "Inquire" in result.aims.steps
    assert "Mirror" in result.aims.steps
    assert "Secure" in result.aims.steps


@pytest.mark.asyncio
async def test_announced_and_inquire_steps_normalize_to_compound_before_announcement(
    classifier_service, mock_gemini_client
):
    mock_gemini_client.generate_text_async.return_value = json.dumps(
        {
            "is_small_talk": False,
            "is_vaccine_relevant": True,
            "aims": {"steps": ["Announce", "Inquire"], "score": 3, "reasons": [], "tips": []},
            "safety_flags": [],
            "person_topic": None,
        }
    )

    result = await classifier_service.classify_turn(
        clinician_message="Maya is due for MMR today. What concerns come up for you?",
        person_last="I'm not sure about it.",
        history=[],
        prior_announced=False,
        prior_phase="PreAnnounce",
        mapping={},
    )

    assert result.aims.step == "Announce+Inquire"


@pytest.mark.asyncio
async def test_announced_and_inquire_steps_after_announcement_do_not_reannounce(
    classifier_service, mock_gemini_client
):
    mock_gemini_client.generate_text_async.return_value = json.dumps(
        {
            "is_small_talk": False,
            "is_vaccine_relevant": True,
            "aims": {"steps": ["Announce", "Inquire"], "score": 2, "reasons": [], "tips": []},
            "safety_flags": [],
            "person_topic": None,
        }
    )

    result = await classifier_service.classify_turn(
        clinician_message="You are still due for MMR. What is most on your mind?",
        person_last="I still have questions.",
        history=[],
        prior_announced=True,
        prior_phase="InquireMirror",
        mapping={},
    )

    assert result.aims.step == "Inquire"
    assert result.aims.step != "Announce+Inquire"


@pytest.mark.asyncio
async def test_classify_turn_caps_tips_and_preserves_null_person_topic(
    classifier_service, mock_gemini_client
):
    mock_gemini_client.generate_text_async.return_value = json.dumps(
        {
            "is_small_talk": False,
            "is_vaccine_relevant": True,
            "aims": {
                "step": "Secure",
                "score": 2,
                "reasons": [],
                "tips": ["First tip", "Second tip"],
            },
            "safety_flags": [],
            "person_topic": None,
        }
    )

    result = await classifier_service.classify_turn(
        clinician_message="Serious reactions are rare, and you can decide what feels right.",
        person_last="That sounds reasonable.",
        history=[],
        prior_announced=True,
        prior_phase="Secure",
        mapping={},
    )

    assert result.aims.tips == ["First tip"]
    assert result.person_topic is None


def test_get_deterministic_fallback_defaults_score_and_appends_fallback(classifier_service):
    with patch("app.aims_engine.evaluate_turn") as evaluate_turn:
        evaluate_turn.return_value = {
            "step": "Mirror",
            "reasons": ["Mirrored concern"],
            "tips": ["Ask if you got that right."],
        }

        result = classifier_service._get_deterministic_fallback(
            clinician_message="It sounds like you're worried.",
            mapping={"Mirror": []},
        )

    assert result.aims.step == "Mirror"
    assert result.aims.score == 2
    assert result.aims.reasons == ["Mirrored concern", "fallback"]
    assert result.aims.tips == ["Ask if you got that right."]
    assert result.reasoning == "deterministic fallback"


def test_get_deterministic_fallback_does_not_duplicate_fallback_reason(classifier_service):
    with patch("app.aims_engine.evaluate_turn") as evaluate_turn:
        evaluate_turn.return_value = {
            "step": "Announce",
            "score": 3,
            "reasons": ["fallback"],
            "tips": [],
        }

        result = classifier_service._get_deterministic_fallback(
            clinician_message="I recommend the MMR vaccine today.",
            mapping={},
        )

    assert result.aims.step == "Announce"
    assert result.aims.score == 3
    assert result.aims.reasons == ["fallback"]


@pytest.mark.asyncio
async def test_classify_turn_strips_json_fences(classifier_service, mock_gemini_client):
    mock_gemini_client.generate_text_async.return_value = """```json
{"is_small_talk": false, "is_vaccine_relevant": true, "aims": {"step": "Inquire", "score": 2, "reasons": ["Asked about concerns"], "tips": ["Keep it open"]}, "safety_flags": [], "reasoning": "Open question."}
```"""

    result = await classifier_service.classify_turn(
        clinician_message="What questions do you have about vaccines?",
        person_last="I'm worried about side effects.",
        history=[],
        prior_announced=True,
        prior_phase="InquireMirror",
        mapping={},
    )

    assert result.aims.step == "Inquire"
    assert result.aims.reasons == ["Asked about concerns"]


@pytest.mark.asyncio
async def test_classify_turn_reraises_actionable_gemini_status_errors(
    classifier_service, mock_gemini_client
):
    class GeminiStatusError(Exception):
        status_code = 403

    err = GeminiStatusError("permission denied")
    mock_gemini_client.generate_text_async.side_effect = err

    with pytest.raises(GeminiStatusError):
        await classifier_service.classify_turn(
            clinician_message="I recommend the MMR today.",
            person_last="Okay.",
            history=[],
            prior_announced=False,
            prior_phase="PreAnnounce",
            mapping={},
        )


@pytest.mark.asyncio
async def test_detect_endgame_returns_parsed_fenced_json(classifier_service, mock_gemini_client):
    mock_gemini_client.generate_text_async.return_value = """```json
{"is_endgame": true, "reason": "accepted_now", "confidence": 0.9}
```"""

    result = await classifier_service.detect_endgame(
        history_text="Parent: Let's do it today.",
        announced=True,
        inquired_concerns=["safety"],
        mirrored_concerns=["safety"],
        secured_concerns=["safety"],
    )

    assert result == {
        "is_endgame": True,
        "reason": "accepted_now",
        "confidence": 0.9,
    }

    prompt = mock_gemini_client.generate_text_async.await_args.args[0]
    assert "Inquired Concerns" in prompt
    assert "Mirrored Concerns" in prompt
    assert "Secured Concerns" in prompt
    assert "Announced" in prompt and "true" in prompt


@pytest.mark.asyncio
async def test_detect_endgame_prompt_includes_transcript_and_concern_lists(
    classifier_service, mock_gemini_client
):
    mock_gemini_client.generate_text_async.return_value = json.dumps(
        {
            "is_endgame": False,
            "reason": "not_resolved",
            "resolution_type": "not_resolved",
            "summary": "",
        }
    )

    await classifier_service.detect_endgame(
        history_text="Doctor: We can send you home with information.\nAssistant: I'd like to read it at home.",
        announced=True,
        inquired_concerns=["trust", "side_effects"],
        mirrored_concerns=["trust"],
        secured_concerns=["trust"],
    )

    prompt = mock_gemini_client.generate_text_async.await_args.args[0]
    assert "Doctor: We can send you home with information." in prompt
    assert "Assistant: I'd like to read it at home." in prompt
    assert "Inquired Concerns" in prompt and "trust, side_effects" in prompt
    assert "Mirrored Concerns" in prompt and "trust" in prompt
    assert "Secured Concerns" in prompt and "trust" in prompt
    assert "Both elements must be present".lower() in prompt.lower()


@pytest.mark.asyncio
async def test_detect_endgame_returns_false_on_error(classifier_service, mock_gemini_client):
    mock_gemini_client.generate_text_async.side_effect = RuntimeError("model down")

    result = await classifier_service.detect_endgame(
        history_text="Parent: Maybe.",
        announced=True,
        inquired_concerns=[],
        mirrored_concerns=[],
        secured_concerns=[],
    )

    assert result == {"is_endgame": False, "reason": "detection_error"}
