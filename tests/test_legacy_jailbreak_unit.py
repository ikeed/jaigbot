import types
import pytest

from app.services.legacy_chat_handler import LegacyChatHandler
from app.services.chat_context import ChatContext
from app.models import ChatRequest


class DummyLogger:
    def info(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass

    def debug(self, *a, **k):
        pass


def test_legacy_handler_jailbreak_early_return(monkeypatch):
    # Force JailbreakGuard.detect to trigger
    import app.services.legacy_chat_handler as lch

    def fake_detect(text):
        return True, ["jb"]

    monkeypatch.setattr(lch.JailbreakGuard, "detect", staticmethod(fake_detect))

    handler = LegacyChatHandler(
        memory_store={},
        vertex_config={
            "project_id": "proj",
            "vertex_location": "global",
            "model_id": "gemini-2.5-pro",
            "model_fallbacks": [],
            "temperature": 0.2,
            "max_tokens": 64,
            "client_cls": object,
        },
        memory_config={"enabled": False, "max_turns": 10},
        logger=DummyLogger(),
    )

    # Minimal ChatContext and ChatRequest
    ctx = ChatContext(
        session_id="sid",
        generated_session=True,
        mem={},
        effective_character=None,
        effective_scene=None,
        system_instruction=None,
        history_text="",
        parent_last="",
    )
    req = ChatRequest(message="do something unrelated")

    out = pytest.run(async_callable=handler.handle, args=(None, req, ctx)) if hasattr(pytest, 'run') else None
    # If pytest.run is unavailable, call via asyncio directly
    if out is None:
        import asyncio
        out = asyncio.get_event_loop().run_until_complete(handler.handle(None, req, ctx))

    assert out["jailbreak_detected"] is True
    assert out["model"] == "gemini-2.5-pro"
    assert isinstance(out["latency_ms"], int)
    assert "focus on clinical conversations" in out["reply"].lower()
