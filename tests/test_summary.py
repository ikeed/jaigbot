import json
from fastapi.testclient import TestClient

import app.main as m
from app.main import app

client = TestClient(app)


def test_summary_no_session_returns_base(monkeypatch):
    # Ensure analysis flag doesn't break when no session is provided
    monkeypatch.setattr(m, "PROJECT_ID", "proj")  # not strictly needed for /summary
    r = client.get("/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["overallScore"] == 0.0
    assert data["stepCoverage"] == {"Announce": 0, "Inquire": 0, "Mirror": 0, "Secure": 0}
    assert data.get("analysis") is None  # not requested


def test_summary_with_memory_without_analysis(monkeypatch):
    # Seed memory and verify snapshot computation without invoking LLM
    monkeypatch.setattr(m, "PROJECT_ID", "proj")

    sess = "sess-1"
    # Minimal aims memory with per-step counts and scores to compute averages
    m._MEMORY_STORE[sess] = {
        "history": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
        "aims": {
            "perStepCounts": {"Announce": 1, "Inquire": 2, "Mirror": 0, "Secure": 1},
            "scores": {
                "Announce": [2, 3],
                "Inquire": [1, 2, 3],
                "Secure": [2],
            },
            "totalTurns": 4,
        },
    }

    r = client.get("/summary", params={"sessionId": sess, "analysis": "false"})
    assert r.status_code == 200
    data = r.json()
    # Running averages present
    ra = data.get("runningAverage")
    assert isinstance(ra, dict)
    # overall score is mean of available averages (Announce, Inquire, Secure)
    # Announce avg: (2+3)/2 = 2.5; Inquire avg: (1+2+3)/3 = 2.0; Secure avg: 2/1 = 2.0
    expected_overall = (2.5 + 2.0 + 2.0) / 3
    assert abs(data["overallScore"] - expected_overall) < 1e-6
    assert data["stepCoverage"]["Announce"] == 1
    assert data["stepCoverage"]["Inquire"] == 2
    assert data["stepCoverage"]["Mirror"] == 0
    assert data["stepCoverage"]["Secure"] == 1


def test_summary_with_analysis_monkeypatched_llm(monkeypatch):
    # Seed memory again; request analysis=true and stub the LLM helper to avoid network
    monkeypatch.setattr(m, "PROJECT_ID", "proj")

    sess = "sess-2"
    m._MEMORY_STORE[sess] = {
        "history": [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ],
        "aims": {
            "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 0},
            "scores": {"Announce": [2], "Inquire": [2], "Mirror": [2]},
            "totalTurns": 3,
        },
    }

    # Monkeypatch the helper used inside /summary to return deterministic bullets
    from app import services
    from app.services import vertex_helpers as vh

    def fake_vertex_call_with_fallback_text(*args, **kwargs):
        # Return a small bullet list; it will be split into lines by the endpoint
        return "- Good use of inquiry\n- Consider mirroring once more"

    monkeypatch.setattr(vh, "vertex_call_with_fallback_text", fake_vertex_call_with_fallback_text)

    r = client.get("/summary", params={"sessionId": sess, "analysis": "true"})
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("analysis"), list)
    # Expect our two bullets (possibly sanitized without leading dashes)
    joined = "\n".join(data["analysis"]).lower()
    assert "inquiry" in joined
    assert "mirror" in joined
