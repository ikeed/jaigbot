from app.services.legacy_chat import LegacyPromptBuilder, VertexTextAttempt


class FakeClientNew:
    def __init__(self, result):
        self._result = result

    def generate_text(self, *, prompt, temperature, max_tokens, system_instruction=None):
        # Return whatever was configured
        return self._result


class FakeClientLegacy:
    def __init__(self, result):
        self._result = result

    def generate_text(self, prompt, temperature, max_tokens):
        return self._result


def test_build_prompt_text_with_history_uses_conversation_prefix():
    mem = {
        "history": [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
    }
    text = LegacyPromptBuilder.build_prompt_text(mem, 8, "What's up?")
    assert text.startswith("Conversation so far:\n")
    assert "User: What's up?\nAssistant:" in text


def test_build_prompt_text_without_history_is_message_only():
    mem = {"history": []}
    text = LegacyPromptBuilder.build_prompt_text(mem, 8, "Ping")
    assert text == "Ping"


def test_vertex_attempt_normalizes_tuple_result():
    client = FakeClientNew(("ok", {"finishReason": "stop", "textLen": 2}))
    text, meta = VertexTextAttempt.attempt(
        client,
        prompt_text="hello",
        temperature=0.2,
        max_tokens=64,
        system_instruction=None,
    )
    assert text == "ok"
    assert meta.get("finishReason") == "stop"


def test_vertex_attempt_normalizes_text_only_result():
    client = FakeClientLegacy("reply text")
    text, meta = VertexTextAttempt.attempt(
        client,
        prompt_text="hello",
        temperature=0.2,
        max_tokens=64,
        system_instruction=None,
    )
    assert text == "reply text"
    # meta synthesized
    assert meta.get("textLen") == len("reply text")
