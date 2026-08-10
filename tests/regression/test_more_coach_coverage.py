from app.config import settings
import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import app.main as m


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
    with (
        patch("app.aims_engine.load_mapping", return_value=mock_mapping),
        patch("app.aims_mapping_loader.load_mapping", return_value=mock_mapping),
    ):
        yield mock_mapping


class GWStub:
    classify_payload = None
    reply_json_payload = None
    person_topic = None
    person_events = None

    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    async def generate_text_async(prompt: str, **kwargs) -> str:
        if "unified" in (prompt or "").lower() or "classify" in (prompt or "").lower():
            # ClassifierService's unified prompt
            aims_payload = GWStub.classify_payload or {"step": "None", "score": 2, "reasons": ["det"], "tips": []}
            payload = {
                "is_small_talk": False,
                "is_vaccine_relevant": True,
                "aims": aims_payload,
                "safety_flags": [],
                "reasoning": "mock",
                "person_topic": GWStub.person_topic,
                "person_events": GWStub.person_events or [],
            }
            return json.dumps(payload)
        
        # Standard reply payload
        payload = GWStub.reply_json_payload or {"patient_reply": "ok"}
        return json.dumps(payload)

    @staticmethod
    def generate_text_json(*, prompt: str, response_schema: dict, system_instruction=None, log_fallback=None) -> str:
        props = (response_schema or {}).get("properties", {}) if isinstance(response_schema, dict) else {}
        is_reply = isinstance(props, dict) and ("patient_reply" in props)
        if is_reply:
            payload = GWStub.reply_json_payload or {"patient_reply": "ok"}
            return json.dumps(payload)
        else:
            payload = GWStub.classify_payload or {"step": None, "score": 2, "reasons": ["det"], "tips": []}
            return json.dumps(payload)

    @staticmethod
    def generate_text(*, prompt: str, system_instruction=None, log_fallback=None) -> str:
        return json.dumps({"patient_reply": "ok"})


def setup_env(monkeypatch):
    GWStub.classify_payload = None
    GWStub.reply_json_payload = None
    GWStub.person_topic = None
    GWStub.person_events = None
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", GWStub)
    monkeypatch.setattr(m, "VertexClient", GWStub)
    monkeypatch.setattr(settings, "AIMS_COACHING_ENABLED", True, raising=False)
    monkeypatch.setattr(m, "MEMORY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PROJECT_ID", "p", raising=False)
    monkeypatch.setattr(settings, "REGION", "us-central1", raising=False)
    monkeypatch.setattr(m, "VERTEX_LOCATION", "us-central1", raising=False)
    
    # AIMS mapping mock is now handled globally by conftest.py


def test_secure_before_mirror_adds_reason_tip_and_caps_score(monkeypatch):
    setup_env(monkeypatch)
    c = TestClient(m.app)
    sess = "secure-pre-mirror"
    # Seed state with an unmirrored concern
    m.MEMORY_STORE[sess] = {
        "history": [{"role": "assistant", "content": "I'm worried about side effects of vaccines"}],
        "aims_state": {
            "announced": True,
            "phase": "InquireMirror",
            "is_undiscovered_concerns": False,
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
    assert "mirroring" in reasons
    assert any("before educating" in t.lower() for t in data["coaching"]["tips"])


def test_topic_mirroring_and_securing_state_updates(monkeypatch):
    setup_env(monkeypatch)
    c = TestClient(m.app)
    sess = "topic-flow"
    # Turn 1: Parent expresses a concern in reply to seed state
    GWStub.classify_payload = {"step": "Announce", "score": 2, "reasons": ["llm"], "tips": []}
    GWStub.person_topic = "side_effects"
    GWStub.reply_json_payload = {"patient_reply": "I'm worried about vaccine side effects."}
    r1 = c.post("/chat", json={"message": "We recommend vaccines today.", "coach": True, "sessionId": sess})
    assert r1.status_code == 200
    
    # Turn 2: Mirror via clinician topic mention
    # We now need another turn to actually seed the concern from the previous turn's reply
    GWStub.classify_payload = {"step": "Inquire", "score": 3, "reasons": ["llm"], "tips": []}
    GWStub.person_topic = "side_effects"
    GWStub.person_events = [
        {
            "event_type": "concern_raised",
            "topic": "side_effects",
            "evidence_spans": ["I'm worried about vaccine side effects."],
        }
    ]
    GWStub.reply_json_payload = {"patient_reply": "ok"}
    r1b = c.post("/chat", json={"message": "What have you heard about side effects?", "coach": True, "sessionId": sess})
    assert r1b.status_code == 200

    # Verify that the concern is now seeded
    assert sess in m.MEMORY_STORE
    assert m.MEMORY_STORE[sess]["aims_state"]["parent_concerns"], "Turn 1b should have seeded parent_concerns from Turn 1's reply"
    
    # Turn 3: Mirror via clinician topic mention
    GWStub.classify_payload = {"step": "Mirror", "score": 3, "reasons": ["llm"], "tips": []}
    GWStub.person_topic = "side_effects"
    GWStub.person_events = [
        {"event_type": "concern_mirrored", "topic": "side_effects"}
    ]
    GWStub.reply_json_payload = {"patient_reply": "ok"}
    r2 = c.post("/chat", json={"message": "It sounds like the side effects worry you.", "coach": True, "sessionId": sess})
    assert r2.status_code == 200
    # Turn 4: Secure via clinician topic mention
    GWStub.classify_payload = {"step": "Secure", "score": 3, "reasons": ["llm"], "tips": []}
    GWStub.person_topic = None
    GWStub.person_events = [
        {"event_type": "concern_secured", "topic": "side_effects"}
    ]
    GWStub.reply_json_payload = {"patient_reply": "ok"}
    r3 = c.post("/chat", json={"message": "For side effects, here is what to expect.", "coach": True, "sessionId": sess})
    assert r3.status_code == 200
    state = m.MEMORY_STORE[sess]["aims_state"]
    assert state["parent_concerns"], "concerns should exist"
    # Ensure concern is mirrored and secured
    assert any(c.get("is_mirrored") for c in state["parent_concerns"]) is True
    assert any(c.get("is_secured") for c in state["parent_concerns"]) is True


def test_zia_style_required_and_safe_reply_seeds_distinct_concerns_auto_resolved(monkeypatch):
    """Concerns raised via person_events with no persona checklist are ad-hoc --
    per the concern-checklist design, ad-hoc entries are auto-resolved
    (is_discovered/is_mirrored/is_secured=True) immediately on creation, so
    they no longer trigger the 'secure before mirror' penalty. That penalty
    still applies to persona-checklist concerns (see
    test_aims_state_service.py's secure-before-mirror coverage)."""
    setup_env(monkeypatch)
    c = TestClient(m.app)
    sess = "zia-required-safe"
    m.MEMORY_STORE[sess] = {
        "history": [
            {"role": "assistant", "content": "Is it required? Is it safe for my son? Is it okay here in Canada?"}
        ],
        "aims_state": {
            "announced": True,
            "phase": "InquireMirror",
            "is_undiscovered_concerns": False,
            "pending_concerns": True,
            "parent_concerns": [],
        },
    }

    GWStub.classify_payload = {"step": "Secure", "score": 3, "reasons": ["llm"], "tips": []}
    GWStub.person_topic = None
    GWStub.person_events = [
        {
            "event_type": "concern_raised",
            "topic": "requirements",
            "evidence_spans": ["Is it required? Is it okay here in Canada?"],
        },
        {
            "event_type": "concern_raised",
            "topic": "side_effects",
            "evidence_spans": ["Is it safe for my son?"],
        },
    ]
    GWStub.reply_json_payload = {"patient_reply": "ok"}
    r2 = c.post(
        "/chat",
        json={
            "message": (
                "The decision is yours, and these vaccines are monitored for safety. "
                "Most side effects are mild."
            ),
            "coach": True,
            "sessionId": sess,
        },
    )
    assert r2.status_code == 200
    data = r2.json()

    reasons = " ".join(data["coaching"]["reasons"]).lower()
    assert "mirroring" not in reasons

    concerns = m.MEMORY_STORE[sess]["aims_state"]["parent_concerns"]
    assert {c["topic"] for c in concerns} == {"requirements", "side_effects"}
    assert all(c["is_mirrored"] and c["is_secured"] for c in concerns)
    # Both concerns are ad-hoc and auto-resolved, so nothing is left pending.
    assert m.MEMORY_STORE[sess]["aims_state"]["pending_concerns"] is False


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
