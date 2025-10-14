import json
import logging
import pytest
from fastapi.testclient import TestClient

from app.main import app


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
    
    # Mock AIMS mapping to prevent Mock object iteration issues
    mock_mapping = {
        "meta": {
            "per_step_classification_markers": {
                "Announce": {"linguistic": ["I recommend", "It's time for"]},
                "Inquire": {"linguistic": ["What concerns", "How are you feeling"]},
                "Mirror": {"linguistic": ["It sounds like", "I'm hearing"]},
                "Secure": {"linguistic": ["It's your decision", "I'm here to support"]}
            }
        }
    }
    monkeypatch.setattr("app.aims_engine.load_mapping", lambda: mock_mapping)
    
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
