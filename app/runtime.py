from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from .memory_store import InMemoryStore, RedisStore


class JsonFormatter(logging.Formatter):
    """Emit each record as one JSON object.

    The app's log call sites mostly build a JSON string and pass it as the log
    message (log_event, the request/exception handlers). Under a plain text
    formatter, aggregators saw that JSON embedded inside a text line -- an
    opaque message, not structured fields. Here a dict-shaped message is merged
    into the output object top-level; plain-string messages land under
    "message". timestamp/severity/logger are set last so a message can never
    clobber them.
    """

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload: dict[str, Any]
        try:
            parsed = json.loads(message)
        except (TypeError, ValueError):
            parsed = None
        payload = dict(parsed) if isinstance(parsed, dict) else {"message": message}
        payload["timestamp"] = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        payload["severity"] = record.levelname
        payload["logger"] = record.name
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


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
    """Build root logging config: local file capture, cloud stdout/stderr.

    Handlers carry a JsonFormatter so every line is one structured JSON
    object (see JsonFormatter). delay=True keeps the local file from being
    created until something actually logs.
    """
    handler: logging.Handler
    if settings.APP_ENV == "local":
        handler = logging.FileHandler("./console.log", delay=True)
    else:
        handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    return {
        "level": getattr(logging, settings.LOG_LEVEL, logging.INFO),
        "handlers": [handler],
    }


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
