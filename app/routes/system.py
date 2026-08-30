from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.constants import (
    ENDPOINT_CONFIG,
    ENDPOINT_DIAGNOSTICS,
    ENDPOINT_HEALTHZ,
    ENDPOINT_HISTORY,
    ENDPOINT_MODELCHECK,
    ENDPOINT_MODELS,
    KEY_GAME_OVER,
)
from app.persona import DEFAULT_CHARACTER, DEFAULT_SCENE


def create_system_router(
    *,
    settings: Any,
    logger: logging.Logger,
    get_memory_store: Callable[..., Any],
    get_model_check: Callable[..., dict],
    get_request_id: Callable[[Request], str | None],
) -> APIRouter:
    router = APIRouter()

    @router.get(ENDPOINT_HEALTHZ)
    async def healthz():
        return {"status": "ok"}

    @router.get(ENDPOINT_HISTORY)
    async def history(
        sessionId: str | None = None,
        full: bool | None = False,
        memory_store=Depends(get_memory_store),
    ):
        """Return conversation history for a session.

        By default returns the trimmed working history as a list of {role, content}.
        Pass ``full=true`` to get the complete untrimmed history with timestamps
        ({role, content, time}).
        """
        try:
            if not (sessionId and settings.MEMORY_ENABLED):
                return {"history": [], "gameOver": False}
            mem = memory_store.get(sessionId) or {}
            game_over = bool(mem.get(KEY_GAME_OVER))
            if full:
                return {"history": mem.get("full_history") or [], "gameOver": game_over}
            hist = mem.get("history") or []
            out: list[dict[str, Any]] = []
            for it in hist:
                try:
                    role = it.get("role")
                    content = it.get("content")
                    if isinstance(role, str) and isinstance(content, str):
                        item: dict[str, Any] = {"role": role, "content": content}
                        coaching = it.get("coaching_data") or it.get("coaching")
                        if isinstance(coaching, dict):
                            item["coaching"] = coaching
                        out.append(item)
                except Exception as e:
                    logger.debug("Failed to parse history item: %s. Error: %s", it, e)
                    continue
            return {"history": out, "gameOver": game_over}
        except Exception as e:
            logger.error("Error retrieving history for session %s: %s", sessionId, e)
            return {"history": [], "gameOver": False}

    @router.get(ENDPOINT_CONFIG)
    async def config(
        memory_store=Depends(get_memory_store),
        model_check: dict = Depends(get_model_check),
    ):
        return {
            "projectId": settings.PROJECT_ID,
            "region": settings.REGION,
            "vertexLocation": settings.VERTEX_LOCATION,
            "modelId": settings.MODEL_ID,
            "aimsClassifierModelId": settings.AIMS_CLASSIFIER_MODEL_ID,
            "aimsClassifierThinkingLevel": settings.AIMS_CLASSIFIER_THINKING_LEVEL,
            "aimsClassifierThinkingBudget": settings.AIMS_CLASSIFIER_THINKING_BUDGET,
            "temperature": settings.TEMPERATURE,
            "maxTokens": settings.MAX_TOKENS,
            "logLevel": settings.LOG_LEVEL,
            "logHeaders": settings.LOG_HEADERS,
            "logRequestBodyMax": settings.LOG_REQUEST_BODY_MAX,
            "logResponsePreviewMax": settings.LOG_RESPONSE_PREVIEW_MAX,
            "allowedOrigins": settings.ALLOWED_ORIGINS,
            "exposeUpstreamError": settings.EXPOSE_UPSTREAM_ERROR,
            "debugMode": settings.DEBUG_MODE,
            "appEnv": settings.APP_ENV,
            "gcsObjectPrefix": settings.gcs_object_prefix,
            "modelFallbacks": settings.MODEL_FALLBACKS,
            "modelAvailable": model_check.get("available"),
            "modelCheck": model_check,
            "autoContinueOnMaxTokens": settings.AUTO_CONTINUE_ON_MAX_TOKENS,
            "maxContinuations": settings.MAX_CONTINUATIONS,
            "suppressVertexAIDeprecation": settings.SUPPRESS_VERTEXAI_DEPRECATION,
            "aimsCoachingEnabled": settings.AIMS_COACHING_ENABLED,
            "aimsCoachingDefault": settings.AIMS_COACHING_DEFAULT,
            "useVertexRest": settings.USE_VERTEX_REST,
            "continueTailChars": settings.CONTINUE_TAIL_CHARS,
            "continuationInstructionEnabled": settings.CONTINUE_INSTRUCTION_ENABLED,
            "minContinueGrowth": settings.MIN_CONTINUE_GROWTH,
            "memoryEnabled": settings.MEMORY_ENABLED,
            "memoryBackend": settings.MEMORY_BACKEND,
            "memoryMaxTurns": settings.MEMORY_MAX_TURNS,
            "memoryTtlSeconds": settings.MEMORY_TTL_SECONDS,
            "redisKeyPrefix": settings.redis_key_prefix,
            "redisFallbackPrefixes": settings.redis_fallback_prefixes,
            "memoryStoreSize": len(memory_store),
            "defaultCharacter": (DEFAULT_CHARACTER if settings.DEBUG_MODE and DEFAULT_CHARACTER else None),
            "defaultScene": (DEFAULT_SCENE if settings.DEBUG_MODE and DEFAULT_SCENE else None),
            "sessionCookie": {
                "name": settings.SESSION_COOKIE_NAME,
                "secure": settings.SESSION_COOKIE_SECURE,
                "sameSite": settings.SESSION_COOKIE_SAMESITE,
                "maxAge": settings.SESSION_COOKIE_MAX_AGE,
            },
        }

    @router.get(ENDPOINT_MODELCHECK)
    async def modelcheck(model_check: dict = Depends(get_model_check)):
        return {"modelId": settings.MODEL_ID, "region": settings.VERTEX_LOCATION, **model_check}

    @router.get(ENDPOINT_DIAGNOSTICS)
    async def diagnostics(memory_store=Depends(get_memory_store)):
        """Expose effective generation settings to help root-cause truncation issues."""
        return {
            "transport": "rest" if settings.USE_VERTEX_REST else "sdk",
            "generationConfig": {
                "temperature": settings.TEMPERATURE,
                "maxOutputTokens": settings.MAX_TOKENS,
                "responseMimeType": "text/plain",
                "thinkingDisabled": None,
            },
            "autoContinueOnMaxTokens": settings.AUTO_CONTINUE_ON_MAX_TOKENS,
            "maxContinuations": settings.MAX_CONTINUATIONS,
            "continueTailChars": settings.CONTINUE_TAIL_CHARS,
            "continuationInstructionEnabled": settings.CONTINUE_INSTRUCTION_ENABLED,
            "minContinueGrowth": settings.MIN_CONTINUE_GROWTH,
            "memory": {
                "enabled": settings.MEMORY_ENABLED,
                "backend": settings.MEMORY_BACKEND,
                "maxTurns": settings.MEMORY_MAX_TURNS,
                "ttlSeconds": settings.MEMORY_TTL_SECONDS,
                "redisKeyPrefix": settings.redis_key_prefix,
                "redisFallbackPrefixes": settings.redis_fallback_prefixes,
                "storeSize": len(memory_store),
            },
            "environment": {
                "appEnv": settings.APP_ENV,
                "gcsObjectPrefix": settings.gcs_object_prefix,
            },
        }

    @router.get(ENDPOINT_MODELS)
    def list_models(request: Request):
        """List available google/publisher models in this project+region using ADC.

        Deliberately sync: google.auth.default() and AuthorizedSession.get() are both
        blocking, and declaring the endpoint `async` ran them on the event loop, stalling
        every concurrent request for the duration. FastAPI dispatches sync endpoints to a
        worker thread.
        """
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        req_id = get_request_id(request)
        started = time.time()
        try:
            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            session = AuthorizedSession(creds)
            loc = settings.VERTEX_LOCATION
            host = "aiplatform.googleapis.com" if str(loc).lower() == "global" else f"{loc}-aiplatform.googleapis.com"
            url = f"https://{host}/v1/projects/{settings.PROJECT_ID}/locations/{loc}/publishers/google/models"
            response = session.get(url)
            latency_ms = int((time.time() - started) * 1000)
            if response.status_code != 200:
                logger.warning(json.dumps({
                    "event": "models_list",
                    "status": "error",
                    "http": response.status_code,
                    "requestId": req_id,
                }))
                return JSONResponse(status_code=502, content={
                    "error": {
                        "message": f"Failed to list models (HTTP {response.status_code})",
                        "code": 502,
                        "requestId": req_id,
                    }
                })

            data = response.json()
            models = data.get("models", [])
            out = [{
                "id": (model.get("name", "").split("/models/")[-1]),
                "displayName": model.get("displayName"),
                "supportedActions": model.get("supportedActions", {}),
            } for model in models]
            logger.info(json.dumps({
                "event": "models_list",
                "status": "ok",
                "latencyMs": latency_ms,
                "count": len(out),
                "requestId": req_id,
            }))
            return {"models": out, "count": len(out), "region": settings.VERTEX_LOCATION}
        except Exception as exc:
            latency_ms = int((time.time() - started) * 1000)
            logger.exception("/models error: %s", exc)
            logger.error(json.dumps({
                "event": "models_list",
                "status": "exception",
                "latencyMs": latency_ms,
                "error": str(exc),
                "requestId": req_id,
            }))
            return JSONResponse(status_code=500, content={
                "error": {"message": "Internal server error", "code": 500, "requestId": req_id}
            })

    return router
