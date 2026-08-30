from app.gemini_client import GeminiClient


def merge(base, add):
    return GeminiClient.merge_with_overlap(base, add)


def test_merge_inserts_space_between_words():
    assert merge("Hello", "world") == "Hello world"
    assert merge("Hello ", "world") == "Hello world"
    assert merge("Hello", " world") == "Hello world"


def test_merge_sentence_boundary_space():
    assert merge("This is fine.", "Next sentence.") == "This is fine. Next sentence."


def test_merge_does_not_add_space_after_open_paren():
    assert merge("Quote (", "text)") == "Quote (text)"


def test_merge_handles_newline_boundary():
    assert merge("Line one\n", "line two") == "Line one line two"


def test_merge_keeps_punctuation_no_extra_space_before():
    assert merge("Hello", ", world") == "Hello, world"


def test_merge_trims_overlap_and_wrapper():
    # Overlap trimming should still insert a space on a word-to-word boundary
    assert merge("abc123", "123xyz") == "abc123 xyz"
    # Wrapper removal like <<<...>>> from continuation hints
    assert merge("Hello world", "<<<tail>>>again") == "Hello world again"


def test_merge_empty_inputs():
    assert merge("", "Now") == "Now"
    assert merge("Start", "") == "Start"


class _Obj:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_extract_response_includes_cached_content_tokens():
    response = _Obj(
        candidates=[
            _Obj(
                content=_Obj(parts=[_Obj(text="ok", thought=False)]),
                finish_reason="STOP",
                safety_ratings=[],
            )
        ],
        usage_metadata=_Obj(
            prompt_token_count=100,
            candidates_token_count=5,
            total_token_count=105,
            cached_content_token_count=80,
        ),
    )

    text, meta = GeminiClient._extract_response(response)

    assert text == "ok"
    assert meta["cachedContentTokens"] == 80
