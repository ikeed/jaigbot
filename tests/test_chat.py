import json
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_chat_validation_empty_message():
    # Empty message should fail Pydantic validation with 422
    r = client.post("/chat", json={"message": ""})
    assert r.status_code == 422
    data = r.json()
    assert "error" in data
    assert data["error"]["code"] == 422
    assert data["error"]["message"] == "Request validation failed"


def test_chat_size_limit_rejected(monkeypatch):
    # Ensure PROJECT_ID is set so we get past the initial check
    import app.main as m
    monkeypatch.setattr(m, "PROJECT_ID", "proj")

    big = "a" * 2049
    r = client.post("/chat", json={"message": big})
    assert r.status_code == 400
    data = r.json()
    assert data["error"]["code"] == 400
    assert "Message too large" in data["error"]["message"]


def test_chat_missing_project_id(monkeypatch):
    # Force PROJECT_ID to None and verify 500 structured error
    import app.main as m
    monkeypatch.setattr(m, "PROJECT_ID", None)

    r = client.post("/chat", json={"message": "hello"})
    assert r.status_code == 500
    data = r.json()
    assert "error" in data
    assert data["error"]["code"] == 500
    # message comes from our detail mapping (normalize to lowercase)
    assert "project_id not set" in json.dumps(data).lower()


def test_chat_success_with_mock(monkeypatch):
    # Mock the vertex helper function used by legacy chat handler
    import app.main as m
    from app.services import legacy_chat_handler

    # Mock the function that actually makes the API call
    def fake_vertex_call(*args, **kwargs):
        prompt = args[5] if len(args) > 5 else kwargs.get('prompt', 'ping')
        return f"echo: {prompt}"

    # Ensure env values are present for route checks
    monkeypatch.setattr(m, "PROJECT_ID", "test-project")
    monkeypatch.setattr(m, "REGION", "us-central1")
    monkeypatch.setattr(m, "MODEL_ID", "gemini-2.5-pro")

    # Mock the function in the handler's module where it's actually imported and used
    monkeypatch.setattr(legacy_chat_handler, "vertex_call_with_fallback_text", fake_vertex_call)

    r = client.post("/chat", json={"message": "ping"})
    assert r.status_code == 200
    data = r.json()
    # The mock should echo back the full prompt which includes system instruction + user message
    assert data["reply"].startswith("echo: ")
    assert "ping" in data["reply"]  # User message should be in the prompt
    assert data["model"] == "gemini-2.5-pro"
    assert isinstance(data["latencyMs"], int)
