import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.vertex import VertexAIError


class GWStub:
    """Stub for app.services.vertex_gateway.VertexGateway used inside main.chat().

    Behavior is controlled via class attributes for simplicity in tests.
    """
    # Controls for classifier JSON path
    classify_payload: dict[str, Any] | None = None
    classify_raises: Exception | None = None
    # Controls for patient reply JSON path
    reply_json_payload: dict[str, Any] | None = None
    reply_json_raises: Exception | None = None
    reply_json_invalid_times: int = 0  # number of times to return invalid JSON for reply

    def __init__(self, *args, **kwargs):
        pass

    def generate_text_json(self, *, prompt: str, response_schema: dict, system_instruction=None, log_fallback=None) -> str:  # noqa: D401
        # Heuristic: detect reply schema vs classifier schema
        props = (response_schema or {}).get("properties", {}) if isinstance(response_schema, dict) else {}
        is_reply = isinstance(props, dict) and ("patient_reply" in props)
        if is_reply:
            if GWStub.reply_json_raises:
                raise GWStub.reply_json_raises
            if GWStub.reply_json_invalid_times > 0:
                GWStub.reply_json_invalid_times -= 1
                return "{"  # invalid JSON
            payload = GWStub.reply_json_payload or {"patient_reply": "ok"}
            return json.dumps(payload)
        else:
            if GWStub.classify_raises:
                raise GWStub.classify_raises
            payload = GWStub.classify_payload or {"step": None, "score": 0, "reasons": [], "tips": []}
            return json.dumps(payload)

    def generate_text(self, *, prompt: str, system_instruction=None, log_fallback=None) -> str:
        # Should not generally be used by current main.py for reply/classifier; keep as fallback
        payload = {"patient_reply": "ok"}
        return json.dumps(payload)


@pytest.fixture(autouse=True)
def reset_gw(monkeypatch):
    # Patch the VertexGateway used inside main._vertex_call / _vertex_call_json
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", GWStub)
    # Sensible defaults for env flags
    monkeypatch.setattr(m, "AIMS_COACHING_ENABLED", True, raising=False)
    monkeypatch.setattr(m, "MEMORY_ENABLED", True, raising=False)
    # Ensure project/region/model vars are present to avoid early 500s
    monkeypatch.setattr(m, "PROJECT_ID", "test-project", raising=False)
    monkeypatch.setattr(m, "REGION", "us-central1", raising=False)
    monkeypatch.setattr(m, "VERTEX_LOCATION", "us-central1", raising=False)
    # Ensure model/fallbacks are set to avoid None
    monkeypatch.setattr(m, "MODEL_ID", "primary", raising=False)
    monkeypatch.setattr(m, "MODEL_FALLBACKS", ["fallback"], raising=False)
    # Reset stub controls each test
    GWStub.classify_payload = None
    GWStub.classify_raises = None
    GWStub.reply_json_payload = None
    GWStub.reply_json_raises = None
    GWStub.reply_json_invalid_times = 0
    yield


def client():
    return TestClient(m.app)


def test_classifier_post_processing_inquire_to_secure_and_tip_trim_and_score_norm(monkeypatch):
    # LLM classifier returns Inquire with score=0 and >1 tips; message has didactic terms and no question
    GWStub.classify_payload = {
        "step": "Inquire",
        "score": 0,
        "reasons": ["llm"],
        "tips": ["t1", "t2"],
    }
    GWStub.reply_json_payload = {"patient_reply": "safe text"}

    # Ensure do_llm = True by making deterministic step not rapport
    def fake_eval(parent_last, clinician, mapping):
        return {"step": "Inquire", "score": 2, "reasons": ["deterministic"], "tips": []}

    monkeypatch.setattr(m, "evaluate_turn", fake_eval, raising=False)

    c = client()
    body = {
        "message": "The studies and evidence about vaccines show safety",  # didactic; no question mark
        "coach": True,
        "sessionId": "s1",
    }
    r = c.post("/chat", json=body)
    assert r.status_code == 200
    data = r.json()
    # Step overridden to Secure and score normalized >=1
    assert data["coaching"]["step"] == "Secure"
    assert data["coaching"]["score"] >= 1
    # Tips trimmed to at most one
    assert isinstance(data["coaching"]["tips"], list)
    assert len(data["coaching"]["tips"]) <= 1


def test_patient_reply_safety_violation_triggers_error_reply(monkeypatch):
    # Classifier returns something valid; reply contains advice-like content
    GWStub.classify_payload = {
        "step": "Announce",
        "score": 2,
        "reasons": ["llm"],
        "tips": [],
    }
    GWStub.reply_json_payload = {"patient_reply": "Take acetaminophen 5 mg every 8 hours"}

    # Ensure do_llm path engaged
    def fake_eval(parent_last, clinician, mapping):
        return {"step": "Announce", "score": 2, "reasons": ["deterministic"], "tips": []}
    monkeypatch.setattr(m, "evaluate_turn", fake_eval, raising=False)

    c = client()
    body = {"message": "Let's discuss vaccines", "coach": True, "sessionId": "s2"}
    r = c.post("/chat", json=body)
    assert r.status_code == 200
    data = r.json()
    # The model's advice triggers a safety rewrite to an error message
    assert data["reply"].startswith("Error: parent persona generated clinician-style advice")


def test_invalid_json_twice_falls_back_based_on_step(monkeypatch):
    # Make deterministic step Mirror via evaluate_turn to control fallback selection
    def fake_eval(parent_last, clinician, mapping):
        return {"step": "Mirror", "score": 2, "reasons": ["deterministic"], "tips": []}

    monkeypatch.setattr(m, "evaluate_turn", fake_eval, raising=False)

    GWStub.classify_payload = {"step": None, "score": 0, "reasons": [], "tips": []}
    # Force two invalid JSON attempts for patient reply
    GWStub.reply_json_invalid_times = 2

    c = client()
    body = {"message": "Let's talk vaccines", "coach": True, "sessionId": "s3"}
    r = c.post("/chat", json=body)
    assert r.status_code == 200
    data = r.json()
    # Fallback text should be one of the known templates; accept a set of possibilities
    low = data["reply"].lower()
    assert (
        ("worried" in low)
        or ("i’m not sure" in low or "i'm not sure" in low)
        or ("thanks for letting me know" in low)
        or ("i appreciate" in low)
    )


