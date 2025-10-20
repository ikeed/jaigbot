import json
import logging

from app.telemetry.events import truncate_for_log, log_event


class StubLogger:
    def __init__(self):
        self.lines = []

    def info(self, msg):
        self.lines.append(msg)


def test_truncate_for_log_caps_length_and_is_safe():
    s = "x" * 10
    assert truncate_for_log(s, 5) == "x" * 5
    # Non-string input becomes str
    assert truncate_for_log(12345, 3) == "123"
    # Graceful if __str__ fails (simulated by object with raising __str__)
    class Bad:
        def __str__(self):
            raise RuntimeError("boom")
    # Should not raise
    out = truncate_for_log(Bad(), 3)
    assert isinstance(out, str)


def test_log_event_basic_and_caps():
    lg = StubLogger()
    big = "y" * 100
    log_event(lg, "test_evt", caps={"requestBody": 10}, requestId="abc", requestBody=big, other=1)
    assert lg.lines, "logger should receive a line"
    payload = json.loads(lg.lines[0])
    assert payload["event"] == "test_evt"
    assert payload["requestId"] == "abc"
    assert payload["other"] == 1
    assert payload["requestBody"] == "y" * 10


def test_log_event_fallback_to_str_on_json_fail(monkeypatch):
    lg = StubLogger()
    class BadObj:
        def __iter__(self):
            # make json.dumps try to iterate into non-serializable
            return self
        def __next__(self):
            raise StopIteration
    # This object is json-serializable but ensure our code path remains safe
    log_event(lg, "evt", bad=BadObj())
    # It should have logged something; we don't assert JSON structure here
    assert lg.lines
