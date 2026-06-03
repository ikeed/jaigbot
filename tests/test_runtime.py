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

    assert local_config["filename"] == "./console.log"
    assert "filename" not in prod_config


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


def test_vertex_client_cache_reuses_by_key_and_clear():
    calls = []

    class Client:
        def __init__(self, *, project, region, model_id):
            calls.append((project, region, model_id))

    cache = runtime.VertexClientCache(client_cls=Client)

    first = cache.get("p", "r", "m")
    second = cache.get("p", "r", "m")
    third = cache.get("p", "r", "other")

    assert first is second
    assert third is not first
    assert calls == [("p", "r", "m"), ("p", "r", "other")]
    assert len(cache) == 2

    cache.clear()

    assert len(cache) == 0


def test_vertex_client_cache_separates_override_client_class():
    class DefaultClient:
        def __init__(self, *, project, region, model_id):
            pass

    class OverrideClient:
        def __init__(self, *, project, region, model_id):
            pass

    cache = runtime.VertexClientCache(client_cls=DefaultClient)

    default = cache.get("p", "r", "m")
    override = cache.get("p", "r", "m", client_cls=OverrideClient)

    assert type(default) is DefaultClient
    assert type(override) is OverrideClient
    assert len(cache) == 2
