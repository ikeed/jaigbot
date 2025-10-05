from app.vertex import VertexClient


def merge(base, add):
    return VertexClient._merge_with_overlap(base, add)


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