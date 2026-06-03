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

    result = await classifier_service.classify_turn(
        clinician_message="I hear you're worried about side effects.",
        person_last="I'm scared of the shots.",
        history=[],
        prior_announced=False,
        prior_phase="PreAnnounce",
        mapping={}
    )

    assert isinstance(result, ClassifierResult)
    assert result.is_small_talk is False
    assert result.aims.step == "Mirror"
    assert result.aims.score == 3
    assert "Reflected concern well" in result.aims.reasons

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

    result = await classifier_service.classify_turn(
        clinician_message="I hear you're worried about side effects.",
        person_last="I'm scared of the shots causing a fever.",
        history=[],
        prior_announced=False,
        prior_phase="PreAnnounce",
        mapping={}
    )

    assert result.person_topic == "side_effects"

@pytest.mark.asyncio
async def test_classify_turn_fallback_on_error(classifier_service, mock_vertex_client):
    # Mock error from Gemini
    mock_vertex_client.generate_text_async.side_effect = Exception("Gemini down")

    result = await classifier_service.classify_turn(
        clinician_message="I recommend the MMR today.",
        person_last="Okay.",
        history=[],
        prior_announced=False,
        prior_phase="PreAnnounce",
        mapping={} # Empty mapping might affect deterministic fallback but evaluate_turn handles it
    )

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
        person_last="I'm scared of side effects.",
        history=[],
        prior_announced=True,
        prior_phase="InquireMirror",
        mapping={}
    )

    assert result.aims.step == "Mirror+Secure+Inquire"
    assert "Inquire" in result.aims.steps
    assert "Mirror" in result.aims.steps
    assert "Secure" in result.aims.steps


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


def test_get_deterministic_fallback_defaults_score_and_appends_fallback(classifier_service):
    with patch("app.services.classifier_service.evaluate_turn") as evaluate_turn:
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
    with patch("app.services.classifier_service.evaluate_turn") as evaluate_turn:
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

