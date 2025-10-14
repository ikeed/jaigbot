import json
from fastapi.testclient import TestClient
import app.main as m


class GWStub2:
    classify_payload = None
    reply_json_payload = None

    def __init__(self, *args, **kwargs):
        pass

    def generate_text_json(self, *, prompt: str, response_schema: dict, system_instruction=None, log_fallback=None) -> str:
        props = (response_schema or {}).get("properties", {}) if isinstance(response_schema, dict) else {}
        is_reply = isinstance(props, dict) and ("patient_reply" in props)
        if is_reply:
            payload = GWStub2.reply_json_payload or {"patient_reply": "ok"}
            return json.dumps(payload)
        else:
            payload = GWStub2.classify_payload or {"step": None, "score": 2, "reasons": ["det"], "tips": []}
            return json.dumps(payload)

    def generate_text(self, *, prompt: str, system_instruction=None, log_fallback=None) -> str:
        return json.dumps({"patient_reply": "ok"})


def test_session_metrics_counts_and_snapshot(monkeypatch):
    # Patch gateway and basic settings
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", GWStub2)
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

    c = TestClient(m.app)

    # Turn 1: Announce; have parent mention a vaccine concern to seed state
    GWStub2.classify_payload = {"step": "Announce", "score": 2, "reasons": ["llm"], "tips": []}
    GWStub2.reply_json_payload = {"patient_reply": "I'm worried about side effects of vaccines."}
    r1 = c.post("/chat", json={"message": "We recommend vaccines today.", "coach": True, "sessionId": "test-sess"})
    assert r1.status_code == 200

    # Turn 2: Mirror+Inquire (compound); should increment both Mirror and Inquire counts
    GWStub2.classify_payload = {"step": "Mirror+Inquire", "score": 3, "reasons": ["llm"], "tips": ["t"]}
    GWStub2.reply_json_payload = {"patient_reply": "Okay."}
    r2 = c.post("/chat", json={"message": "It sounds like you're worried — how can I help?", "coach": True, "sessionId": "test-sess"})
    assert r2.status_code == 200
    data2 = r2.json()
    sess = data2.get("session")
    assert sess is not None
    # totalTurns should be 2, and counts should reflect Mirror and Inquire at least 1 each
    assert sess["totalTurns"] >= 2
    counts = sess["perStepCounts"]
    assert counts["Mirror"] >= 1
    assert counts["Inquire"] >= 1
