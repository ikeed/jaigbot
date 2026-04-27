import pytest
import json
from unittest.mock import AsyncMock, MagicMock
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
        parent_last="I'm scared of the shots.",
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
async def test_classify_turn_with_parent_topic(classifier_service, mock_vertex_client):
    # Mock successful JSON response with parent_topic
    mock_response = {
        "is_small_talk": False,
        "is_vaccine_relevant": True,
        "parent_topic": "side_effects",
        "aims": {
            "step": "Mirror",
            "score": 3,
            "reasons": ["Reflected concern well"],
            "tips": ["Good job"]
        },
        "safety_flags": [],
        "reasoning": "Parent mentioned side effects."
    }
    mock_vertex_client.generate_text_async.return_value = json.dumps(mock_response)

    result = await classifier_service.classify_turn(
        clinician_message="I hear you're worried about side effects.",
        parent_last="I'm scared of the shots causing a fever.",
        history=[],
        prior_announced=False,
        prior_phase="PreAnnounce",
        mapping={}
    )

    assert result.parent_topic == "side_effects"

@pytest.mark.asyncio
async def test_classify_turn_fallback_on_error(classifier_service, mock_vertex_client):
    # Mock error from Gemini
    mock_vertex_client.generate_text_async.side_effect = Exception("Gemini down")

    result = await classifier_service.classify_turn(
        clinician_message="I recommend the MMR today.",
        parent_last="Okay.",
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
async def test_apply_overrides_question_guard(classifier_service):
    # Test that a question ending with '?' overrides Announce to Inquire
    initial_result = ClassifierResult(
        is_small_talk=False,
        is_vaccine_relevant=True,
        aims={
            "step": "Announce",
            "score": 3,
            "reasons": ["LLM mislabel"],
            "tips": []
        }
    )
    
    overridden = classifier_service._apply_overrides(initial_result, "Should we do the MMR today?")
    assert overridden.aims.step == "Inquire"
    assert overridden.aims.score == 2
