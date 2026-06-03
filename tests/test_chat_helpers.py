from app.services.chat_helpers import format_markers


def test_format_markers_returns_empty_string_on_bad_mapping():
    class BadMapping:
        def get(self, *args, **kwargs):
            raise RuntimeError("bad mapping")

    assert format_markers(BadMapping()) == ""
