import json
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_whole_conversation_multi_turns(monkeypatch):
    """
    Exercises a small multi‑turn conversation end‑to‑end using the /chat endpoint
    with session persistence. We inject a fake Vertex client that:
      - records prompts sent for each turn
      - returns deterministic replies so we can assert history growth
    """
    import app.main as m

    # Ensure env values are present for route checks
    monkeypatch.setattr(m, "PROJECT_ID", "test-project")
    monkeypatch.setattr(m, "REGION", "us-central1")
    monkeypatch.setattr(m, "MODEL_ID", "gemini-2.5-pro")

    # Allow cookies over http in TestClient
    monkeypatch.setattr(m, "SESSION_COOKIE_SECURE", False)

    prompts = []
    replies = []
    counter = {"n": 0}  # shared across instances

    class RecordingVertex:
        def __init__(self, project: str, region: str, model_id: str):
            self.project = project
            self.region = region
            self.model_id = model_id

        def generate_text(self, prompt: str, temperature: float, max_tokens: int):
            prompts.append(prompt)
            counter["n"] += 1
            reply = f"reply{counter['n']}"
            replies.append(reply)
            return reply

    monkeypatch.setattr(m, "VertexClient", RecordingVertex)

    turns = [
        "hi there",
        "how are you?",
        "tell me more about vaccines",
        "thanks!",
    ]

    # Turn 1 – should set cookie and return reply1
    r1 = client.post("/chat", json={"message": turns[0]})
    assert r1.status_code == 200
    # Cookie should be set once the first response returns
    assert "set-cookie" in {k.lower() for k in r1.headers.keys()}
    data1 = r1.json()
    assert data1["reply"] == "reply1"
    assert data1["model"] == "gemini-2.5-pro"
    assert isinstance(data1["latencyMs"], int)

    # Subsequent turns – prompts must include growing prior history
    for i in range(1, len(turns)):
        r = client.post("/chat", json={"message": turns[i]})
        assert r.status_code == 200
        data = r.json()
        assert data["reply"] == f"reply{i+1}"
        assert data["model"] == "gemini-2.5-pro"
        assert isinstance(data["latencyMs"], int)

        # Inspect the last prompt sent to the model. It must include a history
        # prefix with the immediately previous user + assistant turns.
        last_prompt = prompts[-1]
        assert "Conversation so far:" in last_prompt
        # The immediately previous user turn must be present
        assert f"User: {turns[i-1]}" in last_prompt
        # The immediately previous assistant reply must be present
        assert f"Assistant: reply{i}" in last_prompt

    # Final sanity: the prompt for the last call should end with the assistant cue
    # to answer the current user message.
    assert prompts[-1].rstrip().endswith("Assistant:")
