import json
import logging
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app


@pytest.fixture(scope="module", autouse=True)
def local_aims_mapping_mock():
    """Module-scoped mock AIMS mapping to prevent 'Mock' object is not iterable errors."""
    mock_mapping = {
        "meta": {
            "per_step_classification_markers": {
                "Announce": {"linguistic": ["I recommend", "It's time for", "She/he is due for", "Today we will", "My recommendation is"]},
                "Inquire": {"linguistic": ["What concerns", "What have you heard", "What matters most", "How are you feeling about", "What would help"]},
                "Mirror": {"linguistic": ["It sounds like", "You're worried that", "I'm hearing", "You want", "You feel"]},
                "Secure": {"linguistic": ["It's your decision", "I'm here to support", "We can", "Options include", "If you'd prefer", "Here's what to expect"]}
            }
        }
    }
    with patch("app.aims_engine.load_mapping", return_value=mock_mapping):
        yield mock_mapping


class FakeVertexInvalidJSON:
    def __init__(self, project: str, region: str, model_id: str):
        pass

    def generate_text(self, *args, **kwargs):
        # Force invalid JSON to trigger retry -> fallback
        return "not-json"


client = TestClient(app)


@pytest.fixture(autouse=True)
def enable_coaching(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "PROJECT_ID", "proj")
    monkeypatch.setattr(m, "REGION", "us-central1")
    monkeypatch.setattr(m, "MODEL_ID", "gemini-2.5-pro")
    monkeypatch.setattr(m, "AIMS_COACHING_ENABLED", True)
    
    # AIMS mapping mock is now handled globally by conftest.py
    
    # Mock at the VertexGateway level since this uses coaching path
    class FakeGatewayInvalidJSON:
        def __init__(self, *args, **kwargs):
            pass
        
        def generate_text(self, *args, **kwargs):
            # Force invalid JSON to trigger retry -> fallback
            return "not-json"
        
        def generate_text_json(self, *args, **kwargs):
            return "not-json"
    
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", FakeGatewayInvalidJSON)
    yield


def test_small_talk_fallback_produces_friendly_reply(caplog):
    caplog.set_level(logging.INFO)
    # Small talk / pleasantries that should classify as non-step
    msg = "Hello Sarah and Liam! So good to see you both — wow, he's getting so big!"

    r = client.post("/chat", json={"message": msg, "coach": True, "sessionId": "st1"})
    assert r.status_code == 200
    data = r.json()
    assert "reply" in data
    reply = data["reply"]
    # Should not be a bland "Okay." and should be the expected fallback response
    assert reply.strip() != "Okay."
    assert reply == "I'm not sure — I have some questions, but I'd like to hear more."

    # Coaching should indicate rapport allowed anytime
    coaching = data.get("coaching") or {}
    reasons = coaching.get("reasons") or []
    joined = " ".join(reasons).lower()
    assert "rapport/pleasantries" in joined
    assert "allowed anytime" in joined
