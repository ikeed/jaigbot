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
    # Provide a fake VertexClient that returns a canned response
    import app.main as m

    class FakeVertex:
        def __init__(self, project: str, region: str, model_id: str):
            self.project = project
            self.region = region
            self.model_id = model_id

        def generate_text(self, prompt: str, temperature: float, max_tokens: int) -> str:
            return f"echo: {prompt}"  # simple echo to validate integration path

    # Ensure env values are present for route checks
    monkeypatch.setattr(m, "PROJECT_ID", "test-project")
    monkeypatch.setattr(m, "REGION", "us-central1")
    monkeypatch.setattr(m, "MODEL_ID", "gemini-2.5-pro")

    # Inject our fake client into the module
    monkeypatch.setattr(m, "VertexClient", FakeVertex)

    r = client.post("/chat", json={"message": "ping"})
    assert r.status_code == 200
    data = r.json()
    assert data["reply"] == "echo: ping"
    assert data["model"] == "gemini-2.5-pro"
    assert isinstance(data["latencyMs"], int)