import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.classifier_service import ClassifierService
from app.models import ClassifierResult

@pytest.fixture
def mock_vertex_client():
    client = MagicMock()
    client.generate_text_async = AsyncMock()
    return client

@pytest.fixture
def classifier_service(mock_vertex_client):
    service = ClassifierService(
        project_id="test-project",
        location="us-central1",
        model_id="gemini-pro",
        client_cls=lambda **kwargs: mock_vertex_client
    )
    return service

@pytest.mark.asyncio
async def test_classify_turn_success(classifier_service, mock_vertex_client):
    # Mock successful JSON response from Gemini
    mock_response = {
        "is_small_talk": False,
        "is_vaccine_relevant": True,
        "aims": {
            "step": "Mirror",
            "score": 3,
            "reasons": ["Reflected concern well"],
            "tips": ["Good job"]
        },
        "safety_flags": [],
        "reasoning": "Test reasoning"
    }
    mock_vertex_client.generate_text_async.return_value = json.dumps(mock_response)

    result = await classifier_service.classify_turn(clinician_message="I hear you're worried about side effects.",
                                                    person_last="I'm scared of the shots.", history=[],
                                                    prior_announced=False, prior_phase="PreAnnounce", mapping={})

    assert isinstance(result, ClassifierResult)
    assert result.is_small_talk is False
    assert result.aims.step == "Mirror"
    assert result.aims.score == 3
    assert "Reflected concern well" in result.aims.reasons


@pytest.mark.asyncio
async def test_classify_turn_prompt_includes_recent_context_and_concern_lists(
    classifier_service, mock_vertex_client
):
    mock_vertex_client.generate_text_async.return_value = json.dumps(
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

    prompt = mock_vertex_client.generate_text_async.await_args.args[0]
    system_instruction = mock_vertex_client.generate_text_async.await_args.kwargs["system_instruction"]
    assert "Doctor: We recommend the MMR vaccine today." in prompt
    assert "Assistant: I thought measles was basically gone." in prompt
    assert "Inquired Concerns: disease_risk, trust" in prompt
    assert "Mirrored Concerns: trust" in prompt
    assert "Phase: InquireMirror" in prompt
    assert "Triple-Move" in system_instruction

@pytest.mark.asyncio
async def test_classify_turn_with_person_topic(classifier_service, mock_vertex_client):
    # Mock successful JSON response with person_topic
    mock_response = {
        "is_small_talk": False,
        "is_vaccine_relevant": True,
        "person_topic": "side_effects",
        "aims": {
            "step": "Mirror",
            "score": 3,
            "reasons": ["Reflected concern well"],
            "tips": ["Good job"]
        },
        "safety_flags": [],
        "reasoning": "Person mentioned side effects."
    }
    mock_vertex_client.generate_text_async.return_value = json.dumps(mock_response)

    result = await classifier_service.classify_turn(clinician_message="I hear you're worried about side effects.",
                                                    person_last="I'm scared of the shots causing a fever.", history=[],
                                                    prior_announced=False, prior_phase="PreAnnounce", mapping={})

    assert result.person_topic == "side_effects"

@pytest.mark.asyncio
async def test_classify_turn_fallback_on_error(classifier_service, mock_vertex_client):
    # Mock error from Gemini
    mock_vertex_client.generate_text_async.side_effect = Exception("Gemini down")

    result = await classifier_service.classify_turn(clinician_message="I recommend the MMR today.", person_last="Okay.",
                                                    history=[], prior_announced=False, prior_phase="PreAnnounce",
                                                    mapping={})

    assert isinstance(result, ClassifierResult)
    # Check that it fell back to deterministic (evaluate_turn)
    # "I recommend the MMR today" should be classified as Announce by deterministic engine
    assert result.aims.step == "Announce"
    # reasons contains "fallback" because our service explicitly adds it in _get_deterministic_fallback
    assert "fallback" in result.aims.reasons

@pytest.mark.asyncio
async def test_triple_move_detection(classifier_service, mock_vertex_client):
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
    mock_vertex_client.generate_text_async.return_value = json.dumps(mock_response)

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
    classifier_service, mock_vertex_client
):
    mock_vertex_client.generate_text_async.return_value = json.dumps(
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
    classifier_service, mock_vertex_client
):
    mock_vertex_client.generate_text_async.return_value = json.dumps(
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
    classifier_service, mock_vertex_client
):
    mock_vertex_client.generate_text_async.return_value = json.dumps(
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
    with patch("app.modules.aims.services.classifier_service.evaluate_turn") as evaluate_turn:
        evaluate_turn.return_value = {
            "step": "Mirror",
            "reasons": ["Reflected concern"],
            "tips": ["Ask if you got that right."],
        }

        result = classifier_service._get_deterministic_fallback(
            clinician_message="It sounds like you're worried.",
            mapping={"Mirror": []},
        )

    assert result.aims.step == "Mirror"
    assert result.aims.score == 2
    assert result.aims.reasons == ["Reflected concern", "fallback"]
    assert result.aims.tips == ["Ask if you got that right."]
    assert result.reasoning == "deterministic fallback"


def test_get_deterministic_fallback_does_not_duplicate_fallback_reason(classifier_service):
    with patch("app.modules.aims.services.classifier_service.evaluate_turn") as evaluate_turn:
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
async def test_classify_turn_strips_json_fences(classifier_service, mock_vertex_client):
    mock_vertex_client.generate_text_async.return_value = """```json
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
async def test_classify_turn_reraises_actionable_vertex_status_errors(
    classifier_service, mock_vertex_client
):
    class VertexStatusError(Exception):
        status_code = 403

    err = VertexStatusError("permission denied")
    mock_vertex_client.generate_text_async.side_effect = err

    with pytest.raises(VertexStatusError):
        await classifier_service.classify_turn(
            clinician_message="I recommend the MMR today.",
            person_last="Okay.",
            history=[],
            prior_announced=False,
            prior_phase="PreAnnounce",
            mapping={},
        )


@pytest.mark.asyncio
async def test_detect_endgame_returns_parsed_fenced_json(classifier_service, mock_vertex_client):
    mock_vertex_client.generate_text_async.return_value = """```json
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

    prompt = mock_vertex_client.generate_text_async.await_args.args[0]
    assert "Inquired Concerns" in prompt
    assert "Mirrored Concerns" in prompt
    assert "Secured Concerns" in prompt
    assert "Announced" in prompt and "true" in prompt


@pytest.mark.asyncio
async def test_detect_endgame_prompt_includes_transcript_and_concern_lists(
    classifier_service, mock_vertex_client
):
    mock_vertex_client.generate_text_async.return_value = json.dumps(
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

    prompt = mock_vertex_client.generate_text_async.await_args.args[0]
    assert "Doctor: We can send you home with information." in prompt
    assert "Assistant: I'd like to read it at home." in prompt
    assert "Inquired Concerns" in prompt and "trust, side_effects" in prompt
    assert "Mirrored Concerns" in prompt and "trust" in prompt
    assert "Secured Concerns" in prompt and "trust" in prompt
    assert "Both elements must be present".lower() in prompt.lower()


@pytest.mark.asyncio
async def test_detect_endgame_returns_false_on_error(classifier_service, mock_vertex_client):
    mock_vertex_client.generate_text_async.side_effect = RuntimeError("model down")

    result = await classifier_service.detect_endgame(
        history_text="Parent: Maybe.",
        announced=True,
        inquired_concerns=[],
        mirrored_concerns=[],
        secured_concerns=[],
    )

    assert result == {"is_endgame": False, "reason": "detection_error"}
