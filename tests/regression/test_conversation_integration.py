from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_whole_conversation_multi_turns(monkeypatch):
    """
    Exercises a small multi‑turn conversation end‑to‑end using the /chat endpoint
    with session persistence. We inject a fake Vertex client that:
      - records prompts sent for each turn
      - returns deterministic replies so we can assert history growth
    """

    # Ensure env values are present for route checks
    monkeypatch.setattr(settings, "PROJECT_ID", "test-project")
    monkeypatch.setattr(settings, "REGION", "us-central1")
    monkeypatch.setattr(settings, "MODEL_ID", "gemini-2.5-pro")
    monkeypatch.setattr(settings, "AIMS_COACHING_ENABLED", False)

    # Allow cookies over http in TestClient
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", False)

    prompts = []
    replies = []
    counter = {"n": 0}  # shared across instances

    # Mock at the VertexGateway level since this uses legacy chat path
    class RecordingGateway:
        def __init__(self, *args, **kwargs):
            pass
        
        @staticmethod
        async def agenerate_text(prompt: str, *args, **kwargs):
            prompts.append(prompt)
            counter["n"] += 1
            reply = f"reply{counter['n']}"
            replies.append(reply)
            return reply
        
        async def agenerate_text_json(self, prompt: str, *args, **kwargs):
            return await self.agenerate_text(prompt, *args, **kwargs)

        @staticmethod
        def generate_text(prompt: str, *args, **kwargs):
            # Fallback for sync calls if any
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # This is tricky in tests, but let's just duplicate the logic
                    prompts.append(prompt)
                    counter["n"] += 1
                    reply = f"reply{counter['n']}"
                    replies.append(reply)
                    return reply
            except Exception:
                pass
            return "sync-not-used"
        
        def generate_text_json(self, prompt: str, *args, **kwargs):
            return self.generate_text(prompt, *args, **kwargs)
    
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", RecordingGateway)

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
        if i > 1:  # Only check history for turns after the second one
            assert "Doctor: hi there" in last_prompt
            assert "Assistant: reply1" in last_prompt
        # The immediately previous user turn must be present
        assert f"Doctor: {turns[i-1]}" in last_prompt
        # The immediately previous assistant reply must be present
        assert f"Assistant: reply{i}" in last_prompt

    # Final sanity: the prompt for the last call should end with the assistant cue
    # to answer the current user message.
    assert prompts[-1].rstrip().endswith("Assistant:")
