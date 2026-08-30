"""The classifier's model and thinking config must survive the trip to ClassifierService.

`_gemini_config()` in app/main.py supplies classifier_model_id / classifier_thinking_level
/ classifier_thinking_budget, but ChatOrchestrator dropped them when re-packing the
config dict for AimsCoachingHandler. AimsGeminiConfig.from_mapping then fell back to
MODEL_ID with no thinking level, so classification silently ran on the main model.
Nothing asserted on it, so the regression was invisible for a month.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture
def captured_classifiers(monkeypatch):
    """Record every ClassifierService constructed during a request."""
    from app.services import aims_coaching_handler as handler_module

    created: list[dict] = []
    real_cls = handler_module.ClassifierService

    class RecordingClassifierService(real_cls):  # type: ignore[misc, valid-type]
        def __init__(self, **kwargs):
            created.append(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr(handler_module, "ClassifierService", RecordingClassifierService)
    return created


def _post_coached_turn():
    return client.post(
        "/chat",
        json={
            "sessionId": "classifier-config-test",
            "message": "I am worried about the side effects.",
            "coach": True,
        },
    )


def test_classifier_receives_its_configured_model_and_thinking(
    monkeypatch, captured_classifiers
):
    monkeypatch.setattr(settings, "PROJECT_ID", "test-project")
    monkeypatch.setattr(settings, "REGION", "us-central1")
    monkeypatch.setattr(settings, "AIMS_COACHING_ENABLED", True)
    monkeypatch.setattr(settings, "MODEL_ID", "gemini-3.6-flash")
    monkeypatch.setattr(settings, "AIMS_CLASSIFIER_MODEL_ID", "gemini-3.5-flash-lite")
    monkeypatch.setattr(settings, "AIMS_CLASSIFIER_THINKING_LEVEL", "minimal")
    monkeypatch.setattr(settings, "AIMS_CLASSIFIER_THINKING_BUDGET", 128)

    _post_coached_turn()

    assert captured_classifiers, "no ClassifierService was constructed for a coached turn"
    kwargs = captured_classifiers[0]

    assert kwargs["model_id"] == "gemini-3.5-flash-lite", (
        f"classifier ran on {kwargs['model_id']!r}; expected the configured "
        "AIMS_CLASSIFIER_MODEL_ID. The config was dropped in transit."
    )
    assert kwargs["thinking_level"] == "minimal"
    assert kwargs["thinking_budget"] == 128


def test_classifier_falls_back_to_main_model_when_unset(
    monkeypatch, captured_classifiers
):
    monkeypatch.setattr(settings, "PROJECT_ID", "test-project")
    monkeypatch.setattr(settings, "REGION", "us-central1")
    monkeypatch.setattr(settings, "AIMS_COACHING_ENABLED", True)
    monkeypatch.setattr(settings, "MODEL_ID", "gemini-3.6-flash")
    monkeypatch.setattr(settings, "AIMS_CLASSIFIER_MODEL_ID", "")
    monkeypatch.setattr(settings, "AIMS_CLASSIFIER_THINKING_LEVEL", None)
    monkeypatch.setattr(settings, "AIMS_CLASSIFIER_THINKING_BUDGET", None)

    _post_coached_turn()

    assert captured_classifiers
    kwargs = captured_classifiers[0]
    assert kwargs["model_id"] == "gemini-3.6-flash"
    assert kwargs["thinking_level"] is None
    assert kwargs["thinking_budget"] is None
