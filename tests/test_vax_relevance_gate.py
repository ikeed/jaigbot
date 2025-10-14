import json
import pytest
from fastapi.testclient import TestClient

from app.main import app


class FakeVertexAimsJSON:
    """
    Returns valid JSON for both classifier and patient-reply paths.
    - If prompt includes the classifier tag, emit a classification payload based on the clinician text.
    - Otherwise emit a safe patient reply.
    """
    def __init__(self, project: str, region: str, model_id: str):
        self.calls = 0

    def generate_text(self, *args, **kwargs):
        prompt = args[0] if args else kwargs.get("prompt", "")
        self.calls += 1
        if isinstance(prompt, str) and prompt.startswith("[AIMS_CLASSIFY]"):
            # Simple rules for the test
            if "mmr" in prompt.lower() or "it's time for" in prompt.lower():
                return json.dumps({
                    "step": "Announce",
                    "score": 3,
                    "reasons": ["test: announce"],
                    "tips": []
                })
            # Mirror + Inquire case without explicit vaccine token in clinician text
            if "is there anything else on your mind?" in prompt.lower() or "what's on your mind" in prompt.lower():
                return json.dumps({
                    "step": "Mirror+Inquire",
                    "score": 3,
                    "reasons": ["test: mirror+inquire"],
                    "tips": []
                })
            # Default
            return json.dumps({
                "step": None,
                "score": 0,
                "reasons": ["test: default"],
                "tips": []
            })
        # Patient reply path
        return json.dumps({"patient_reply": "Okay, thanks for explaining."})


client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "PROJECT_ID", "proj")
    monkeypatch.setattr(m, "REGION", "us-central1")
    monkeypatch.setattr(m, "MODEL_ID", "gemini-2.5-pro")
    monkeypatch.setattr(m, "AIMS_COACHING_ENABLED", True)
    monkeypatch.setattr(m, "VertexClient", FakeVertexAimsJSON)
    
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
    
    yield


def test_parent_context_keeps_vax_related_when_clinician_does_not_repeat_tokens():
    # Step 1: Announce (sets prior announced state)
    sid = "gate-ctx-1"
    r1 = client.post("/chat", json={
        "message": "It's time for Liam's MMR vaccine today. How does that sound?",
        "coach": True,
        "sessionId": sid,
    })
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["coaching"]["step"] == "Announce"

    # Step 2: Mirror+Inquire without explicit vaccine token in the clinician text
    clinician_turn = (
        "Yes, one hears a lot of things online these days and some of it is quite scary. "
        "You're definitely not alone in that. We'll cover that today. "
        "Before we do that, is there anything else on your mind?"
    )
    r2 = client.post("/chat", json={
        "message": clinician_turn,
        "coach": True,
        "sessionId": sid,
    })
    assert r2.status_code == 200
    data2 = r2.json()
    # Should not be nulled by vaccine-relevance gating (exact step can vary by FSM)
    assert data2["coaching"]["step"] is not None
