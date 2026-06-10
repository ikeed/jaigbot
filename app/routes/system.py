from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.persona import DEFAULT_CHARACTER, DEFAULT_SCENE
from app.constants import (
    ENDPOINT_HEALTHZ,
    ENDPOINT_HISTORY,
    ENDPOINT_CONFIG,
    ENDPOINT_MODELCHECK,
    ENDPOINT_DIAGNOSTICS,
    ENDPOINT_MODELS,
)


def create_system_router(
    *,
    settings: Any,
    logger: logging.Logger,
    get_memory_store: Callable[..., Any],
    get_model_check: Callable[..., dict],
    get_active_module: Callable[..., Any],
    get_module_registry: Callable[..., Any],
    get_request_id: Callable[[Request], str | None],
) -> APIRouter:
    router = APIRouter()

    @router.get(ENDPOINT_HEALTHZ)
    async def healthz():
        return {"status": "ok"}

    @router.get(ENDPOINT_HISTORY)
    async def history(
        sessionId: Optional[str] = None,
        full: Optional[bool] = False,
        memory_store=Depends(get_memory_store),
    ):
        """Return conversation history for a session.

        By default returns the trimmed working history as a list of {role, content}.
        Pass ``full=true`` to get the complete untrimmed history with timestamps
        ({role, content, time}).
        """
        try:
            if not (sessionId and settings.MEMORY_ENABLED):
                return {"history": []}
            mem = memory_store.get(sessionId) or {}
            if full:
                return {"history": mem.get("full_history") or []}
            hist = mem.get("history") or []
            out = []
            for it in hist:
                try:
                    role = it.get("role")
                    content = it.get("content")
                    if isinstance(role, str) and isinstance(content, str):
                        out.append({"role": role, "content": content})
                except Exception as e:
                    logger.debug("Failed to parse history item: %s. Error: %s", it, e)
                    continue
            return {"history": out}
        except Exception as e:
            logger.error("Error retrieving history for session %s: %s", sessionId, e)
            return {"history": []}

    @router.get(ENDPOINT_CONFIG)
    async def config(
        memory_store=Depends(get_memory_store),
        model_check: dict = Depends(get_model_check),
        active_module=Depends(get_active_module),
        module_registry=Depends(get_module_registry),
    ):
        active_module_manifest = getattr(active_module, "manifest", None)
        available_modules = []
        for module in module_registry.list_modules():
            manifest = getattr(module, "manifest", None)
            if manifest is None:
                continue
            available_modules.append(
                {
                    "id": manifest.id,
                    "displayName": manifest.display_name,
                    "chatProfileName": manifest.chat_profile_name,
                    "supportsIntro": manifest.supports_intro,
                    "supportsFeedback": manifest.supports_feedback,
                    "supportsSummary": manifest.supports_summary,
                    "storagePrefix": manifest.storage_prefix,
                    "frontendJsBundles": list(manifest.frontend_js_bundles),
                    "frontendCss": manifest.frontend_css,
                    "branding": (
                        {
                            "appTitle": manifest.branding.app_title,
                            "avatarName": manifest.branding.avatar_name,
                            "logoAsset": manifest.branding.logo_asset,
                            "loadingText": manifest.branding.loading_text,
                        }
                        if manifest.branding
                        else None
                    ),
                }
            )
        return {
            "projectId": settings.PROJECT_ID,
            "region": settings.REGION,
            "vertexLocation": settings.VERTEX_LOCATION,
            "modelId": settings.MODEL_ID,
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
            "activeModule": (
                {
                    "id": active_module_manifest.id,
                    "displayName": active_module_manifest.display_name,
                    "chatProfileName": active_module_manifest.chat_profile_name,
                    "storagePrefix": active_module_manifest.storage_prefix,
                    "archiveSchemaVersion": active_module_manifest.archive_schema_version,
                    "supportsIntro": active_module_manifest.supports_intro,
                    "supportsFeedback": active_module_manifest.supports_feedback,
                    "supportsSummary": active_module_manifest.supports_summary,
                    "frontendJsBundles": list(active_module_manifest.frontend_js_bundles),
                    "frontendCss": active_module_manifest.frontend_css,
                    "branding": (
                        {
                            "appTitle": active_module_manifest.branding.app_title,
                            "avatarName": active_module_manifest.branding.avatar_name,
                            "logoAsset": active_module_manifest.branding.logo_asset,
                            "loadingText": active_module_manifest.branding.loading_text,
                        }
                        if active_module_manifest.branding
                        else None
                    ),
                }
                if active_module_manifest
                else None
            ),
            "availableModules": available_modules,
        }

    @router.get(ENDPOINT_MODELCHECK)
    async def modelcheck(model_check: dict = Depends(get_model_check)):
        return {"modelId": settings.MODEL_ID, "region": settings.VERTEX_LOCATION, **model_check}

    @router.get(ENDPOINT_DIAGNOSTICS)
    async def diagnostics(memory_store=Depends(get_memory_store), active_module=Depends(get_active_module)):
        """Expose effective generation settings to help root-cause truncation issues."""
        active_module_manifest = getattr(active_module, "manifest", None)
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
                "activeModuleId": (active_module_manifest.id if active_module_manifest else None),
            },
        }

    @router.get(ENDPOINT_MODELS)
    async def list_models(request: Request):
        """List available google/publisher models in this project+region using ADC."""
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
