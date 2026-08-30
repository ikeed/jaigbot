from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from .memory_store import InMemoryStore, RedisStore


def delegating_lifespan(backend_app: Any) -> Any:
    """Lifespan for a parent app that runs a mounted backend app's own lifespan.

    Starlette does not run lifespan handlers for mounted sub-apps, so in
    unified mode (run_app.py mounting app.main under /api) the backend's
    startup work -- the model preflight, app.state seeding -- silently never
    executed. Delegating to the backend's own lifespan_context keeps unified
    mode in sync with whatever app.main's lifespan does now or in the future,
    instead of duplicating its body here.
    """

    @asynccontextmanager
    async def _lifespan(_parent: Any):
        async with backend_app.router.lifespan_context(backend_app):
            yield

    return _lifespan


def get_logging_config(settings: Any) -> dict[str, Any]:
    """Build root logging config: local file capture, cloud stdout/stderr."""
    config: dict[str, Any] = {
        "level": getattr(logging, settings.LOG_LEVEL, logging.INFO),
        "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
    }
    if settings.APP_ENV == "local":
        config["filename"] = "./console.log"
    return config


def create_memory_store(settings: Any, logger: logging.Logger | None = None) -> Any:
    """Create the configured memory store with the existing local fallback behavior."""
    try:
        if settings.MEMORY_ENABLED and settings.MEMORY_BACKEND == "redis":
            return RedisStore(
                url=settings.REDIS_URL,
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                password=settings.REDIS_PASSWORD,
                prefix=settings.redis_key_prefix,
                fallback_prefixes=settings.redis_fallback_prefixes,
                ttl=settings.MEMORY_TTL_SECONDS,
                logger=logger,
            )
        return InMemoryStore(persist_path=settings.MEMORY_PERSIST_PATH)
    except Exception as exc:
        if logger:
            logger.warning("Falling back to in-memory store: %s", exc)
        settings.MEMORY_BACKEND = "memory"
        return InMemoryStore(persist_path=settings.MEMORY_PERSIST_PATH)
