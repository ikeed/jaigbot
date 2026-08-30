import logging
from types import SimpleNamespace

from app import runtime


def test_create_memory_store_passes_logger_to_redis(monkeypatch):
    expected_store = object()
    expected_logger = logging.getLogger("test")
    captured = {}

    def fake_redis_store(**kwargs):
        captured.update(kwargs)
        return expected_store

    monkeypatch.setattr(runtime, "RedisStore", fake_redis_store)
    settings = SimpleNamespace(
        MEMORY_ENABLED=True,
        MEMORY_BACKEND="redis",
        REDIS_URL=None,
        REDIS_HOST="localhost",
        REDIS_PORT=6379,
        REDIS_DB=0,
        REDIS_PASSWORD=None,
        redis_key_prefix="aims:session:",
        redis_fallback_prefixes=[],
        MEMORY_TTL_SECONDS=3600,
        MEMORY_PERSIST_PATH=None,
        APP_ENV="local",
    )

    store = runtime.create_memory_store(settings, expected_logger)

    assert store is expected_store
    assert captured["logger"] is expected_logger


def test_logging_config_writes_to_file_only_for_local_env():
    local_config = runtime.get_logging_config(SimpleNamespace(APP_ENV="local", LOG_LEVEL="DEBUG"))
    prod_config = runtime.get_logging_config(SimpleNamespace(APP_ENV="prod", LOG_LEVEL="INFO"))

    (local_handler,) = local_config["handlers"]
    (prod_handler,) = prod_config["handlers"]
    assert isinstance(local_handler, logging.FileHandler)
    assert local_handler.baseFilename.endswith("console.log")
    assert isinstance(prod_handler, logging.StreamHandler)
    assert not isinstance(prod_handler, logging.FileHandler)
    assert isinstance(local_handler.formatter, runtime.JsonFormatter)
    assert isinstance(prod_handler.formatter, runtime.JsonFormatter)
    assert local_config["level"] == logging.DEBUG
    assert prod_config["level"] == logging.INFO


def _format_record(msg: str, *, level=logging.INFO, exc_info=None) -> dict:
    import json

    record = logging.LogRecord(
        name="app.test", level=level, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=exc_info,
    )
    return json.loads(runtime.JsonFormatter().format(record))


def test_json_formatter_merges_dict_shaped_messages_top_level():
    out = _format_record('{"event": "request_start", "path": "/chat"}')

    assert out["event"] == "request_start"
    assert out["path"] == "/chat"
    assert "message" not in out
    assert out["severity"] == "INFO"
    assert out["logger"] == "app.test"
    assert "timestamp" in out


def test_json_formatter_puts_plain_strings_under_message():
    out = _format_record("something plain happened", level=logging.WARNING)

    assert out["message"] == "something plain happened"
    assert out["severity"] == "WARNING"


def test_json_formatter_message_cannot_clobber_base_fields():
    out = _format_record('{"severity": "spoofed", "logger": "spoofed", "event": "x"}')

    assert out["severity"] == "INFO"
    assert out["logger"] == "app.test"
    assert out["event"] == "x"


def test_json_formatter_attaches_exc_info():
    import sys

    try:
        raise ValueError("boom")
    except ValueError:
        out = _format_record('{"event": "request_error"}', level=logging.ERROR, exc_info=sys.exc_info())

    assert out["event"] == "request_error"
    assert "ValueError: boom" in out["exc_info"]


def test_create_memory_store_uses_in_memory_when_redis_disabled(monkeypatch):
    captured = {}

    def fake_in_memory_store(*, persist_path):
        captured["persist_path"] = persist_path
        return "memory-store"

    monkeypatch.setattr(runtime, "InMemoryStore", fake_in_memory_store)
    settings = SimpleNamespace(
        MEMORY_ENABLED=False,
        MEMORY_BACKEND="redis",
        MEMORY_PERSIST_PATH="/tmp/memory.json",
    )

    assert runtime.create_memory_store(settings) == "memory-store"
    assert captured["persist_path"] == "/tmp/memory.json"


def test_create_memory_store_falls_back_when_redis_creation_fails(monkeypatch):
    warnings = []

    def fail_redis_store(**kwargs):
        raise RuntimeError("redis down")

    def fake_in_memory_store(*, persist_path):
        return {"persist_path": persist_path}

    monkeypatch.setattr(runtime, "RedisStore", fail_redis_store)
    monkeypatch.setattr(runtime, "InMemoryStore", fake_in_memory_store)
    settings = SimpleNamespace(
        MEMORY_ENABLED=True,
        MEMORY_BACKEND="redis",
        REDIS_URL=None,
        REDIS_HOST="localhost",
        REDIS_PORT=6379,
        REDIS_DB=0,
        REDIS_PASSWORD=None,
        redis_key_prefix="aims:session:",
        redis_fallback_prefixes=[],
        MEMORY_TTL_SECONDS=3600,
        MEMORY_PERSIST_PATH="/tmp/fallback.json",
    )
    logger = SimpleNamespace(warning=lambda *args: warnings.append(args))

    store = runtime.create_memory_store(settings, logger)

    assert store == {"persist_path": "/tmp/fallback.json"}
    assert settings.MEMORY_BACKEND == "memory"
    assert warnings
