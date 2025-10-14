import json
from fastapi.testclient import TestClient
from unittest.mock import patch
import app.main as m


class GWStub:
    classify_payload = None
    reply_json_payload = None

    def __init__(self, *args, **kwargs):
        pass

    def generate_text_json(self, *, prompt: str, response_schema: dict, system_instruction=None, log_fallback=None) -> str:
        props = (response_schema or {}).get("properties", {}) if isinstance(response_schema, dict) else {}
        is_reply = isinstance(props, dict) and ("patient_reply" in props)
        if is_reply:
            payload = GWStub.reply_json_payload or {"patient_reply": "ok"}
            return json.dumps(payload)
        else:
            payload = GWStub.classify_payload or {"step": None, "score": 2, "reasons": ["det"], "tips": []}
            return json.dumps(payload)

    def generate_text(self, *, prompt: str, system_instruction=None, log_fallback=None) -> str:
        return json.dumps({"patient_reply": "ok"})


def setup_env(monkeypatch):
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", GWStub)
    monkeypatch.setattr(m, "AIMS_COACHING_ENABLED", True, raising=False)
    monkeypatch.setattr(m, "MEMORY_ENABLED", True, raising=False)
    monkeypatch.setattr(m, "PROJECT_ID", "p", raising=False)
    monkeypatch.setattr(m, "REGION", "us-central1", raising=False)
    monkeypatch.setattr(m, "VERTEX_LOCATION", "us-central1", raising=False)
    
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


def test_secure_before_mirror_adds_reason_tip_and_caps_score(monkeypatch):
    setup_env(monkeypatch)
    c = TestClient(m.app)
    sess = "secure-pre-mirror"
    # Seed state with an unmirrored concern
    m._MEMORY_STORE[sess] = {
        "history": [{"role": "assistant", "content": "I'm worried about side effects of vaccines"}],
        "aims_state": {
            "announced": True,
            "phase": "InquireMirror",
            "first_inquire_done": True,
            "pending_concerns": True,
            "parent_concerns": [
                {"desc": "side effects", "topic": "side_effects", "is_mirrored": False, "is_secured": False}
            ],
        },
    }
    # Classifier says Secure prematurely
    GWStub.classify_payload = {"step": "Secure", "score": 3, "reasons": ["llm"], "tips": []}
    GWStub.reply_json_payload = {"patient_reply": "ok"}
    r = c.post("/chat", json={"message": "Studies show it's safe.", "coach": True, "sessionId": sess})
    assert r.status_code == 200
    data = r.json()
    # Score capped and reason/tip injected
    assert data["coaching"]["score"] <= 2
    reasons = " ".join(data["coaching"]["reasons"]).lower()
    assert "securing before mirroring" in reasons
    assert any("before educating" in t.lower() for t in data["coaching"]["tips"])


def test_topic_mirroring_and_securing_state_updates(monkeypatch):
    setup_env(monkeypatch)
    c = TestClient(m.app)
    sess = "topic-flow"
    # Turn 1: Parent expresses a concern in reply to seed state
    GWStub.classify_payload = {"step": "Announce", "score": 2, "reasons": ["llm"], "tips": []}
    GWStub.reply_json_payload = {"patient_reply": "I'm worried about vaccine side effects."}
    r1 = c.post("/chat", json={"message": "We recommend vaccines today.", "coach": True, "sessionId": sess})
    assert r1.status_code == 200
    # Turn 2: Mirror via clinician topic mention
    GWStub.classify_payload = {"step": "Mirror", "score": 3, "reasons": ["llm"], "tips": []}
    GWStub.reply_json_payload = {"patient_reply": "ok"}
    r2 = c.post("/chat", json={"message": "It sounds like the side effects worry you.", "coach": True, "sessionId": sess})
    assert r2.status_code == 200
    # Turn 3: Secure via clinician topic mention
    GWStub.classify_payload = {"step": "Secure", "score": 3, "reasons": ["llm"], "tips": []}
    GWStub.reply_json_payload = {"patient_reply": "ok"}
    r3 = c.post("/chat", json={"message": "For side effects, here is what to expect.", "coach": True, "sessionId": sess})
    assert r3.status_code == 200
    state = m._MEMORY_STORE[sess]["aims_state"]
    assert state["parent_concerns"], "concerns should exist"
    # Ensure concern is mirrored and secured
    assert any(c.get("is_mirrored") for c in state["parent_concerns"]) is True
    assert any(c.get("is_secured") for c in state["parent_concerns"]) is True


def test_running_average_populated(monkeypatch):
    setup_env(monkeypatch)
    c = TestClient(m.app)
    sess = "avg-sess"
    # Two turns for Secure with different scores
    GWStub.classify_payload = {"step": "Secure", "score": 1, "reasons": ["llm"], "tips": []}
    GWStub.reply_json_payload = {"patient_reply": "ok"}
    r1 = c.post("/chat", json={"message": "It's your decision; here are options.", "coach": True, "sessionId": sess})
    assert r1.status_code == 200
    GWStub.classify_payload = {"step": "Secure", "score": 3, "reasons": ["llm"], "tips": []}
    r2 = c.post("/chat", json={"message": "We'll support whatever you choose.", "coach": True, "sessionId": sess})
    assert r2.status_code == 200
    data2 = r2.json()
    avg = data2["session"]["runningAverage"].get("Secure")
    assert avg is not None
    assert 1.0 <= avg <= 3.0
