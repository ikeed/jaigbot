import json
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_cookie_issued_and_memory_persists(monkeypatch):
    """
    First call should set a session cookie. Second call should include previous
    history in the prompt that is sent to the Vertex client. We simulate the
    Vertex client with a fake that records the prompt it was called with.
    """
    import app.main as m

    # Ensure env values are present for route checks
    monkeypatch.setattr(m, "PROJECT_ID", "test-project")
    monkeypatch.setattr(m, "REGION", "us-central1")
    monkeypatch.setattr(m, "MODEL_ID", "gemini-2.5-pro")
    # Ensure cookies work over http in TestClient by disabling the Secure flag
    monkeypatch.setattr(m, "SESSION_COOKIE_SECURE", False)

    prompts = []

    class RecordingVertex:
        def __init__(self, project: str, region: str, model_id: str):
            self.project = project
            self.region = region
            self.model_id = model_id

        def generate_text(self, prompt: str, temperature: float, max_tokens: int):
            prompts.append(prompt)
            # Return a small reply to ensure it's stored in memory too
            return "ack"

    monkeypatch.setattr(m, "VertexClient", RecordingVertex)

    # 1) First call without sessionId should set a cookie
    r1 = client.post("/chat", json={"message": "ping"})
    assert r1.status_code == 200
    assert "set-cookie" in {k.lower() for k in r1.headers.keys()}
    data1 = r1.json()
    assert data1["reply"] == "ack"

    # 2) Second call should see previous history and include it in the prompt
    r2 = client.post("/chat", json={"message": "next"})
    assert r2.status_code == 200

    # Verify that the second prompt contains a history prefix with the prior user turn
    assert len(prompts) >= 2
    second_prompt = prompts[-1]
    assert "Conversation so far:" in second_prompt
    assert "User: ping" in second_prompt
    assert second_prompt.rstrip().endswith("Assistant:")
