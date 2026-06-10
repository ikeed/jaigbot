import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .core.registry import build_builtin_registry
from .http_handlers import get_request_id as _get_request_id, install_http_handlers
from .vertex import VertexClient
from .runtime import VertexClientCache, create_memory_store, get_logging_config
from .routes.chat import create_chat_router
from .routes.session import create_session_router
from .routes.summary import create_summary_router
from .routes.system import create_system_router
from .services.model_preflight import run_model_preflight
from .constants import APP_TITLE, APP_VERSION

_VERTEX_CLIENT_CACHE = VertexClientCache()

logging.basicConfig(**get_logging_config(settings))
logger = logging.getLogger("app")

MEMORY_STORE = create_memory_store(settings, logger)


@asynccontextmanager
async def _lifespan(application: FastAPI):
    """Application lifespan: run startup tasks before yielding, cleanup after."""
    application.state.memory_store = MEMORY_STORE
    application.state.vertex_client_cache = _VERTEX_CLIENT_CACHE
    module_registry = build_builtin_registry(settings=settings)
    active_module = module_registry.get_active_module(active_module=settings.ACTIVE_MODULE)
    application.state.module_registry = module_registry
    application.state.active_module = active_module
    logger.info(
        "Active training module resolved: id=%s display_name=%s",
        active_module.module_id,
        active_module.display_name,
    )
    await _model_preflight(application)
    yield


app = FastAPI(title=APP_TITLE, version=APP_VERSION, lifespan=_lifespan)


def get_memory_store(request: Request):
    return getattr(request.app.state, "memory_store", MEMORY_STORE)


def get_model_check(request: Request) -> dict:
    return getattr(request.app.state, "model_check", {"available": "unknown"})


def get_active_module(request: Request):
    active_module = getattr(request.app.state, "active_module", None)
    if active_module is not None:
        return active_module
    module_registry = build_builtin_registry(settings=settings)
    return module_registry.get_active_module(active_module=settings.ACTIVE_MODULE)

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
    get_active_module=get_active_module,
    get_request_id=_get_request_id,
))
app.include_router(create_summary_router(
    settings=settings,
    logger=logger,
    get_memory_store=get_memory_store,
    get_active_module=get_active_module,
    vertex_client_cls=VertexClient,
))
app.include_router(create_session_router(
    settings=settings,
    logger=logger,
    get_memory_store=get_memory_store,
    get_active_module=get_active_module,
))


def _vertex_config() -> dict:
    return {
        "project_id": settings.PROJECT_ID,
        "region": settings.REGION,
        "vertex_location": settings.VERTEX_LOCATION,
        "model_id": settings.MODEL_ID,
        "model_fallbacks": settings.MODEL_FALLBACKS,
        "temperature": settings.TEMPERATURE,
        "max_tokens": settings.MAX_TOKENS,
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


def _chat_orchestrator(memory_store=None, active_module=None):
    from .services.chat_orchestrator import ChatOrchestrator

    return ChatOrchestrator(
        memory_store=memory_store or MEMORY_STORE,
        session_cookie_settings=_session_cookie_settings(),
        memory_config=_memory_config(),
        aims_config=_aims_config(),
        vertex_config=_vertex_config(),
        debug_config=_debug_config(),
        logger=logger,
        active_module=active_module or build_builtin_registry(settings=settings).get_active_module(
            active_module=settings.ACTIVE_MODULE
        ),
    )


def get_chat_orchestrator(memory_store=Depends(get_memory_store), active_module=Depends(get_active_module)):
    return _chat_orchestrator(memory_store=memory_store, active_module=active_module)


app.include_router(create_chat_router(
    settings=settings,
    get_chat_orchestrator=get_chat_orchestrator,
))
