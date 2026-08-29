import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .http_handlers import get_request_id as _get_request_id, install_http_handlers
from .vertex import VertexClient
from .runtime import create_memory_store, get_logging_config
from .routes.chat import create_chat_router
from .routes.session import create_session_router
from .routes.summary import create_summary_router
from .routes.system import create_system_router
from .services.model_preflight import run_model_preflight
from .constants import APP_TITLE, APP_VERSION


logging.basicConfig(**get_logging_config(settings))
logger = logging.getLogger("app")

MEMORY_STORE = create_memory_store(settings, logger)


@asynccontextmanager
async def _lifespan(application: FastAPI):
    """Application lifespan: run startup tasks before yielding, cleanup after."""
    application.state.memory_store = MEMORY_STORE
    await _model_preflight(application)
    yield


app = FastAPI(title=APP_TITLE, version=APP_VERSION, lifespan=_lifespan)


def get_memory_store(request: Request):
    return getattr(request.app.state, "memory_store", MEMORY_STORE)


def get_model_check(request: Request) -> dict:
    return getattr(request.app.state, "model_check", {"available": "unknown"})


def _vertex_client_factory(**kwargs: Any) -> Any:
    """Construct a VertexClient, resolving the class at call time.

    include_router() runs at import, so handing the class itself to a router factory
    freezes the real VertexClient into that router's closure, where monkeypatching
    app.main.VertexClient can never reach it. Callers only ever call this with keyword
    arguments (see VertexGateway), so a factory is a transparent substitute.
    """
    return VertexClient(**kwargs)

# Optional CORS
if settings.ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        max_age=3600,
    )


async def _model_preflight(application: FastAPI):
    """Best-effort check whether the configured settings.MODEL_ID exists in the selected Vertex location.
    Stores tri-state availability in app.state.model_check: { available: true|false|"unknown", ... }.
    Never raises; only logs.
    """
    await run_model_preflight(application, settings=settings, logger=logger)


install_http_handlers(app, settings=settings, logger=logger)


app.include_router(create_system_router(
    settings=settings,
    logger=logger,
    get_memory_store=get_memory_store,
    get_model_check=get_model_check,
    get_request_id=_get_request_id,
))
app.include_router(create_summary_router(
    settings=settings,
    logger=logger,
    get_memory_store=get_memory_store,
    vertex_client_cls=_vertex_client_factory,
))
app.include_router(create_session_router(
    settings=settings,
    logger=logger,
    get_memory_store=get_memory_store,
))


def _vertex_config() -> dict:
    return {
        "project_id": settings.PROJECT_ID,
        "region": settings.REGION,
        "vertex_location": settings.VERTEX_LOCATION,
        "model_id": settings.MODEL_ID,
        "model_fallbacks": settings.MODEL_FALLBACKS,
        "classifier_model_id": settings.AIMS_CLASSIFIER_MODEL_ID,
        "classifier_thinking_level": settings.AIMS_CLASSIFIER_THINKING_LEVEL,
        "classifier_thinking_budget": settings.AIMS_CLASSIFIER_THINKING_BUDGET,
        "temperature": settings.TEMPERATURE,
        "max_tokens": settings.MAX_TOKENS,
        "classify_temperature": settings.AIMS_CLASSIFY_TEMPERATURE,
        "classify_max_tokens": settings.AIMS_CLASSIFY_MAX_TOKENS,
        "classify_budget_s": settings.AIMS_CLASSIFY_BUDGET_S,
        "reply_max_tokens": settings.AIMS_REPLY_MAX_TOKENS,
        "heuristic_fallback_enabled": settings.AIMS_HEURISTIC_FALLBACK_ENABLED,
        # Pass client class from app.main so tests can monkeypatch m.VertexClient.
        "client_cls": VertexClient,
    }


def _memory_config() -> dict:
    return {
        "enabled": settings.MEMORY_ENABLED,
        "max_turns": settings.MEMORY_MAX_TURNS,
        "ttl_seconds": settings.MEMORY_TTL_SECONDS,
    }


def _session_cookie_settings() -> dict:
    return {
        "name": settings.SESSION_COOKIE_NAME,
        "secure": settings.SESSION_COOKIE_SECURE,
        "samesite": settings.SESSION_COOKIE_SAMESITE,
        "max_age": settings.SESSION_COOKIE_MAX_AGE,
    }


def _aims_config() -> dict:
    return {
        "enabled": settings.AIMS_COACHING_ENABLED,
        "force_default": settings.AIMS_COACHING_DEFAULT,
    }


def _debug_config() -> dict:
    return {
        "expose_upstream_error": settings.EXPOSE_UPSTREAM_ERROR,
        "log_response_preview_max": settings.LOG_RESPONSE_PREVIEW_MAX,
    }


def _chat_orchestrator(memory_store=None):
    from .services.chat_orchestrator import ChatOrchestrator

    return ChatOrchestrator(
        memory_store=memory_store or MEMORY_STORE,
        session_cookie_settings=_session_cookie_settings(),
        memory_config=_memory_config(),
        aims_config=_aims_config(),
        vertex_config=_vertex_config(),
        debug_config=_debug_config(),
        logger=logger,
    )


def get_chat_orchestrator(memory_store=Depends(get_memory_store)):
    return _chat_orchestrator(memory_store=memory_store)


app.include_router(create_chat_router(
    settings=settings,
    get_chat_orchestrator=get_chat_orchestrator,
))
