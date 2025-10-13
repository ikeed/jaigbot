import json
from fastapi.testclient import TestClient
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


def test_non_vax_gating_sets_null_step(monkeypatch):
    setup_env(monkeypatch)
    c = TestClient(m.app)
    # LLM classifies to Announce, but message is not vaccine-related; expect step None
    GWStub.classify_payload = {"step": "Announce", "score": 2, "reasons": ["llm"], "tips": []}
    GWStub.reply_json_payload = {"patient_reply": "ok"}
    r = c.post("/chat", json={"message": "How's your day going?", "coach": True, "sessionId": "g1"})
    assert r.status_code == 200
    data = r.json()
    assert data["coaching"]["step"] is None


def test_tip_suppression_when_all_concerns_mirrored(monkeypatch):
    setup_env(monkeypatch)
    c = TestClient(m.app)
    sess = "tip-sess"
    # Preload state: no unmirrored concerns remain
    m._MEMORY_STORE[sess] = {
        "history": [{"role": "assistant", "content": "I'm worried about side effects of vaccines"}],
        "aims_state": {
            "announced": True,
            "phase": "InquireMirror",
            "first_inquire_done": True,
            "pending_concerns": False,
            "parent_concerns": [
                {"desc": "side effects", "topic": "side_effects", "is_mirrored": True, "is_secured": True}
            ],
        },
    }
    # Now LLM suggests Inquire with a tip containing 'what else'; it should be suppressed
    GWStub.classify_payload = {"step": "Inquire", "score": 2, "reasons": ["llm"], "tips": ["Before asking what else, mirror concerns"]}
    GWStub.reply_json_payload = {"patient_reply": "ok"}
    r = c.post("/chat", json={"message": "How can I help?", "coach": True, "sessionId": sess})
    assert r.status_code == 200
    data = r.json()
    assert data["coaching"]["tips"] == []


def test_announce_after_inquiry_gets_reason_and_score_capped(monkeypatch):
    setup_env(monkeypatch)
    c = TestClient(m.app)
    sess = "ann-after-inq"
    m._MEMORY_STORE[sess] = {
        "history": [{"role": "assistant", "content": "I'm worried about side effects of vaccines"}],
        "aims_state": {
            "announced": False,
            "phase": "InquireMirror",
            "first_inquire_done": True,
            "pending_concerns": True,
            "parent_concerns": [
                {"desc": "side effects", "topic": "side_effects", "is_mirrored": True, "is_secured": False}
            ],
        },
    }
    GWStub.classify_payload = {"step": "Announce", "score": 3, "reasons": ["llm"], "tips": []}
    GWStub.reply_json_payload = {"patient_reply": "ok"}
    r = c.post("/chat", json={"message": "We recommend vaccines today.", "coach": True, "sessionId": sess})
    assert r.status_code == 200
    data = r.json()
    # Score should be capped to at most 2 and reasons should contain guidance about Announce after inquiry
    assert data["coaching"]["score"] <= 2
    assert any("announce after inquiry" in s.lower() for s in data["coaching"]["reasons"])
