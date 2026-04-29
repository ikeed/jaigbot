import json
import logging
import os
import time
import uuid
import asyncio
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .vertex import VertexClient, VertexAIError

# Lazy, cached Vertex client per (project, region, model, class) to avoid re-initializing
# a new SDK client on every request while still allowing tests to monkeypatch VertexClient.
_VERTEX_CLIENT_CACHE = {}

def _get_vertex_client(project: str, region: str, model_id: str):
    key = (project, region, model_id, VertexClient)
    client = _VERTEX_CLIENT_CACHE.get(key)
    if client is None:
        client = VertexClient(project=project, region=region, model_id=model_id)
        _VERTEX_CLIENT_CACHE[key] = client
    return client
from .persona import DEFAULT_CHARACTER, DEFAULT_SCENE
from .services.conversation_service import (
    maybe_add_parent_concern as svc_maybe_add_parent_concern,
    mark_mirrored_multi as svc_mark_mirrored_multi,
    mark_secured_by_topic as svc_mark_secured_by_topic,
)
from .telemetry.events import (
    log_event as telemetry_log_event,
    truncate_for_log as telemetry_truncate,
)
from .services.session_service import SessionService, CookieSettings

from .config import settings

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("app")

# Memory store abstraction (factored into app.memory_store for readability)
from .memory_store import InMemoryStore, RedisStore

# Instantiate store with fallback
try:
    if settings.MEMORY_ENABLED and settings.MEMORY_BACKEND == "redis":
        _MEMORY_STORE = RedisStore(
            url=settings.REDIS_URL,
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            prefix=settings.REDIS_PREFIX,
        )
    else:
        _MEMORY_STORE = InMemoryStore()
except Exception:
    _MEMORY_STORE = InMemoryStore()
    settings.MEMORY_BACKEND = "memory"

app = FastAPI(title="AIMSBot (Vertex AI)", version="0.1.0")

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


# Model availability preflight (diagnostics-only)
@app.on_event("startup")
async def _model_preflight():
    """Best-effort check whether the configured settings.MODEL_ID exists in the selected Vertex location.
    Stores tri-state availability in app.state.model_check: { available: true|false|"unknown", ... }.
    Never raises; only logs.
    """
    app.state.model_check = {"available": "unknown", "modelId": settings.MODEL_ID, "region": settings.VERTEX_LOCATION}
    if not settings.VALIDATE_MODEL_ON_STARTUP:
        app.state.model_check["reason"] = "disabled_by_env"
        return
    if not settings.PROJECT_ID:
        app.state.model_check["reason"] = "no_project_id"
        return
    try:
        import google.auth  # type: ignore
        from google.auth.transport.requests import AuthorizedSession  # type: ignore
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = AuthorizedSession(creds)

        attempts: list[dict] = []

        def try_get(api_version: str) -> tuple[int, str]:
            loc = settings.VERTEX_LOCATION
            host = "aiplatform.googleapis.com" if str(loc).lower() == "global" else f"{loc}-aiplatform.googleapis.com"
            url = (
                f"https://{host}/{api_version}/projects/{settings.PROJECT_ID}"
                f"/locations/{loc}/publishers/google/models/{settings.MODEL_ID}"
            )
            r = session.get(url)
            attempts.append({"apiVersion": api_version, "url": url, "httpStatus": r.status_code})
            return r.status_code, url

        # Use stable v1 endpoint only (skip beta)
        primary = "v1"
        code, url_primary = try_get(primary)
        app.state.model_check["apiVersion"] = primary
        app.state.model_check["urlPrimary"] = url_primary
        app.state.model_check["httpStatusPrimary"] = code

        if code == 404:
            # Default to unknown on 404; do a v1 models list to avoid false negatives
            app.state.model_check["available"] = "unknown"
            loc = settings.VERTEX_LOCATION
            host = "aiplatform.googleapis.com" if str(loc).lower() == "global" else f"{loc}-aiplatform.googleapis.com"
            list_url = f"https://{host}/v1/projects/{settings.PROJECT_ID}/locations/{loc}/publishers/google/models"
            app.state.model_check["listUrl"] = list_url
            rlist = session.get(list_url)
            app.state.model_check["listHttpStatus"] = rlist.status_code
            matched = False
            if rlist.status_code == 200:
                try:
                    data = rlist.json()
                except Exception:
                    data = {}
                models = data.get("models", []) or []
                app.state.model_check["listCount"] = len(models)
                matched = any(((m.get("name", "").split("/models/")[-1]) == settings.MODEL_ID) for m in models)
            app.state.model_check["listMatched"] = matched
            if matched:
                app.state.model_check["available"] = True
        else:
            app.state.model_check["httpStatus"] = code
            app.state.model_check["available"] = True if code == 200 else "unknown"

        # Record all attempts for debugging
        app.state.model_check["urlsTried"] = attempts
        # Precompute the generateContent base URL(s) that the Vertex client would use
        try:
            loc = settings.VERTEX_LOCATION
            host = "aiplatform.googleapis.com" if str(loc).lower() == "global" else f"{loc}-aiplatform.googleapis.com"
            gen_primary = "v1"
            base_gen_url = f"https://{host}/{gen_primary}/projects/{settings.PROJECT_ID}/locations/{loc}/publishers/google/models/{settings.MODEL_ID}:generateContent"
            app.state.model_check["baseGenerateUrlPrimary"] = base_gen_url
        except Exception:
            pass

    except Exception as e:
        # ADC missing or network error — mark unknown
        try:
            logger.info(json.dumps({
                "event": "model_preflight",
                "status": "exception",
                "error": str(e),
                "modelId": settings.MODEL_ID,
                "region": settings.VERTEX_LOCATION,
            }))
        except Exception:
            logger.info("model preflight error: %s", e)
        app.state.model_check["available"] = "unknown"
        app.state.model_check["error"] = str(e)


# Exception handlers to surface better errors with request correlation
@app.exception_handler(HTTPException)
async def on_http_exception(request: Request, exc: HTTPException):
    # Normalize all HTTP exceptions into a consistent error envelope
    req_id = _get_request_id(request)
    logger.warning(json.dumps({
        "event": "http_exception",
        "status": exc.status_code,
        "detail": exc.detail,
        "requestId": req_id,
        "path": request.url.path,
        "method": request.method,
    }))

    # Build a flat error object: { message, code, requestId, ... }
    if isinstance(exc.detail, dict):
        base = exc.detail.get("error", exc.detail).copy()
    elif isinstance(exc.detail, list):
        base = {"errors": exc.detail}
    else:
        base = {"message": str(exc.detail)}

    # Ensure required fields
    base.setdefault("message", "")
    base.setdefault("code", exc.status_code)
    base.setdefault("requestId", req_id)

    return JSONResponse(status_code=exc.status_code, content={"error": base})


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    req_id = _get_request_id(request)

    # Safely log the request body in a JSON-serializable way
    body_logged = None
    if request.method in ("POST", "PUT", "PATCH"):
        try:
            raw = await request.body()
        except Exception:
            raw = b""
        if raw:
            try:
                body_logged = json.loads(raw.decode("utf-8"))
            except Exception:
                try:
                    body_logged = raw.decode("utf-8", errors="replace")
                except Exception:
                    body_logged = "<binary>"

    logger.warning(json.dumps({
        "event": "request_validation_error",
        "errors": exc.errors(),
        "body": body_logged,
        "requestId": req_id,
        "path": request.url.path,
        "method": request.method,
    }))
    return JSONResponse(status_code=422, content={
        "error": {"message": "Request validation failed", "code": 422, "requestId": req_id, "errors": exc.errors()}})


@app.exception_handler(Exception)
async def on_unhandled_exception(request: Request, exc: Exception):
    req_id = _get_request_id(request)
    # This will include the traceback to stderr and our JSON line after
    logger.exception("Unhandled application exception: %s", exc)
    logger.error(json.dumps({
        "event": "unhandled_exception",
        "error": str(exc),
        "requestId": req_id,
        "path": request.url.path,
        "method": request.method,
    }))
    return JSONResponse(status_code=500,
                        content={"error": {"message": "Internal server error", "code": 500, "requestId": req_id}})


# Simple structured logging middleware with request id and capped body logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    # Request ID: prefer inbound headers, else generate
    req_id = request.headers.get("x-cloud-trace-context") or request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = req_id

    start = time.time()
    # Read and restore body for downstream handlers
    try:
        body_bytes = await request.body()
    except Exception:
        body_bytes = b""

    # Restore the request stream so downstream can read body
    async def receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}

    try:
        request._receive = receive  # type: ignore[attr-defined]
    except Exception:
        pass

    # Prepare log details
    body_preview = body_bytes[:settings.LOG_REQUEST_BODY_MAX]
    body_logged = None
    if body_preview:
        try:
            body_logged = json.loads(body_preview.decode("utf-8"))
            # Redact persona/scene fields unless in debug mode
            if not settings.DEBUG_MODE and isinstance(body_logged, dict):
                if "character" in body_logged:
                    body_logged["character"] = "<hidden>"
                if "scene" in body_logged:
                    body_logged["scene"] = "<hidden>"
        except Exception:
            # fallback to string preview
            try:
                body_logged = body_preview.decode("utf-8", errors="replace")
            except Exception:
                body_logged = "<binary>"

    headers_logged = None
    if settings.LOG_HEADERS:
        # Redact common sensitive headers
        redact = {"authorization", "cookie", "set-cookie"}
        headers_logged = {k: ("<redacted>" if k.lower() in redact else v) for k, v in request.headers.items()}

    logger.info(
        json.dumps(
            {
                "event": "request_start",
                "method": request.method,
                "path": request.url.path,
                "client": request.client.host if request.client else None,
                "requestId": req_id,
                "bodySize": len(body_bytes) if body_bytes else 0,
                "body": body_logged,
                "headers": headers_logged,
            }
        )
    )

    try:
        response = await call_next(request)
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        logger.exception("Unhandled exception processing request: %s", e)
        logger.error(
            json.dumps(
                {
                    "event": "request_error",
                    "requestId": req_id,
                    "latencyMs": latency_ms,
                    "error": str(e),
                }
            )
        )
        # Let FastAPI's exception handling continue
        raise

    # Attach request id back to the response for client correlation
    try:
        response.headers["x-request-id"] = req_id
    except Exception:
        pass

    latency_ms = int((time.time() - start) * 1000)
    # Choose log level based on status code
    status_code = getattr(response, "status_code", None)
    end_event = json.dumps(
        {
            "event": "request_end",
            "method": request.method,
            "path": request.url.path,
            "status": status_code,
            "latencyMs": latency_ms,
            "requestId": req_id,
        }
    )
    try:
        if isinstance(status_code, int) and status_code >= 500:
            logger.error(end_event)
        elif isinstance(status_code, int) and status_code >= 400:
            logger.warning(end_event)
        else:
            logger.info(end_event)
    except Exception:
        logger.info(end_event)

    return response




@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/history")
async def history(sessionId: Optional[str] = None):
    """Return raw conversation history for a session as a list of {role, content}.
    If the session is missing or memory disabled, return an empty list.
    """
    try:
        if not (sessionId and settings.MEMORY_ENABLED):
            return {"history": []}
        mem = _MEMORY_STORE.get(sessionId) or {}
        hist = mem.get("history") or []
        # Ensure items are objects with role/content strings
        out = []
        for it in hist:
            try:
                role = it.get("role")
                content = it.get("content")
                if isinstance(role, str) and isinstance(content, str):
                    out.append({"role": role, "content": content})
            except Exception:
                continue
        return {"history": out}
    except Exception:
        return {"history": []}


@app.get("/summary")
async def summary(sessionId: Optional[str] = None, analysis: Optional[bool] = False):
    """Return an aggregated AIMS summary for a session.

    Stable contract keys: overallScore, stepCoverage, strengths, growthAreas.
    Optional: when analysis=true, includes an LLM-authored 'analysis' bullet list
    using full transcript, AIMS scores, and aims_mapping.json.
    """
    base = {"overallScore": 0.0, "stepCoverage": {"Announce": 0, "Inquire": 0, "Mirror": 0, "Secure": 0}, "strengths": [], "growthAreas": []}
    if not sessionId or not settings.MEMORY_ENABLED:
        if analysis:
            base["analysis"] = []
        return base
    mem = _MEMORY_STORE.get(sessionId) or {}
    aims = mem.get("aims") or {}
    per_counts = {"Announce": 0, "Inquire": 0, "Mirror": 0, "Secure": 0}
    per_counts.update(aims.get("perStepCounts", {}))
    # compute simple averages
    running_avg: dict[str, float] = {}
    for k, arr in (aims.get("scores", {}) or {}).items():
        if arr:
            try:
                running_avg[k] = sum(arr)/len(arr)
            except Exception:
                pass
    # overall: mean of available averages
    overall = (sum(running_avg.values())/len(running_avg)) if running_avg else 0.0
    base.update({
        "overallScore": overall,
        "stepCoverage": per_counts,
        "runningAverage": running_avg,
        "strengths": [],
        "growthAreas": [],
        "totalTurns": aims.get("totalTurns", 0),
    })

    if not analysis:
        return base

    # Build transcript
    transcript = ""
    try:
        hist = mem.get("history") or []
        parts = []
        for item in hist:
            role = item.get("role") or "assistant"
            author = "Doctor" if role == "user" else "Patient"
            txt = (item.get("content") or "").strip()
            if txt:
                parts.append(f"{author}: {txt}")
        transcript = "\n".join(parts)
    except Exception:
        transcript = ""

    # Load aims mapping JSON
    mapping = getattr(app.state, "aims_mapping", None)
    if mapping is None:
        try:
            from .aims_engine import load_mapping
            mapping = load_mapping()
            app.state.aims_mapping = mapping
        except Exception:
            mapping = {}

    metrics_blob = json.dumps({
        "totalTurns": aims.get("totalTurns", 0),
        "perStepCounts": per_counts,
        "runningAverage": aims.get("runningAverage", {}),
    }, ensure_ascii=False)
    mapping_blob = json.dumps(mapping or {}, ensure_ascii=False)

    # Render prompt and call Vertex to obtain analysis bullets
    try:
        from app.prompts.aims import build_summary_analysis_prompt as _build_summary_analysis_prompt
        prompt = _build_summary_analysis_prompt(metrics_blob=metrics_blob, mapping_blob=mapping_blob, transcript=transcript)

        from .services.vertex_helpers import vertex_call_with_fallback_text
        # Use Flash for summary analysis (faster, schema-light); keep Pro as fallback
        narrative = await asyncio.to_thread(
            vertex_call_with_fallback_text,
            project=settings.PROJECT_ID,
            region=settings.VERTEX_LOCATION,
            primary_model="gemini-2.5-flash",
            fallbacks=[settings.MODEL_ID] + list(settings.MODEL_FALLBACKS or []),
            temperature=min(settings.TEMPERATURE, 0.2),
            max_tokens=min(settings.MAX_TOKENS, 384),
            prompt=prompt,
            system_instruction=None,
            log_path="summary_analysis",
            logger=logger,
            client_cls=VertexClient,
        )
        narrative = (narrative or "").strip()
        bullets_raw = [ln for ln in narrative.splitlines() if ln.strip()]
        try:
            from app.services.coach_post import sanitize_endgame_bullets as _sanitize
            bullets = _sanitize(bullets_raw)
        except Exception:
            bullets = [ln.strip(" -\t") for ln in bullets_raw]

        # Enforce consistency with metrics: do not allow bullets that contradict step coverage
        try:
            import re
            def _enforce_metrics_consistency(bullets_in: list[str], step_counts: dict[str, int]) -> list[str]:
                present = {k for k, v in (step_counts or {}).items() if isinstance(v, int) and v > 0}
                pat = re.compile(r"\b(Announce|Inquire|Mirror|Secure)\b.*\b(skipped|missing|didn’t happen|did not happen|not used)\b", re.IGNORECASE)
                cleaned: list[str] = []
                for b in bullets_in or []:
                    m = pat.search(b or "")
                    if m and (m.group(1) in present):
                        step = m.group(1)
                        rewrites = {
                            "Announce": "Announce occurred — keep it concise and invite input (e.g., ‘It’s MMR today — how does that sound?’).",
                            "Inquire": "Inquire was present — prioritize open-ended questions and pause for the full answer.",
                            "Mirror": "Mirror was used — keep reflecting the exact worry before educating.",
                            "Secure": "Secure was present — share one tailored fact, link to the concern, and check understanding.",
                        }
                        cleaned.append(rewrites.get(step, b))
                    else:
                        cleaned.append(b)
                # de-duplicate preserving order
                out, seen = [], set()
                for x in cleaned:
                    if x not in seen:
                        out.append(x); seen.add(x)
                return out
            bullets = _enforce_metrics_consistency(bullets, per_counts)
        except Exception:
            pass

        base["analysis"] = bullets
    except Exception as e:
        telemetry_log_event(logger, "summary_analysis_failed", sessionId=sessionId, error=str(e))
        base["analysis"] = []

    return base


from .models import Coaching, SessionMetrics, ChatRequest


def _get_request_id(request: Request) -> Optional[str]:
    # X-Cloud-Trace-Context: traceId/spanId;o=traceTrue
    h = request.headers.get("x-cloud-trace-context") or request.headers.get("x-request-id")
    if h:
        return h
    # fallback to middleware-provided id or generate one
    try:
        return getattr(request.state, "request_id", None) or str(uuid.uuid4())
    except Exception:
        return str(uuid.uuid4())


@app.post("/chat")
async def chat(req: Request, body: ChatRequest):
    """Main chat endpoint using the new ChatOrchestrator."""
    # Enforce settings.PROJECT_ID presence for live calls to align with tests/contract
    if not settings.PROJECT_ID:
        # Raise HTTPException to be normalized by our exception handler
        raise HTTPException(status_code=500, detail={
            "error": {"message": "settings.PROJECT_ID not set — configure the settings.PROJECT_ID environment variable.", "code": 500}
        })

    # Build config structures for orchestrator
    vertex_config = {
        "project_id": settings.PROJECT_ID,
        "region": settings.REGION,
        "vertex_location": settings.VERTEX_LOCATION,
        "model_id": settings.MODEL_ID,
        "model_fallbacks": settings.MODEL_FALLBACKS,
        "temperature": settings.TEMPERATURE,
        "max_tokens": settings.MAX_TOKENS,
        # Pass client class from app.main so tests can monkeypatch m.VertexClient
        "client_cls": VertexClient,
    }
    
    memory_config = {
        "enabled": settings.MEMORY_ENABLED,
        "max_turns": settings.MEMORY_MAX_TURNS,
        "ttl_seconds": settings.MEMORY_TTL_SECONDS,
    }
    
    session_cookie_settings = {
        "name": settings.SESSION_COOKIE_NAME,
        "secure": settings.SESSION_COOKIE_SECURE,
        "samesite": settings.SESSION_COOKIE_SAMESITE,
        "max_age": settings.SESSION_COOKIE_MAX_AGE,
    }
    
    aims_config = {
        "enabled": settings.AIMS_COACHING_ENABLED,
        "force_default": (os.getenv("AIMS_COACHING_DEFAULT", "false").lower() == "true"),
    }
    
    debug_config = {
        "expose_upstream_error": settings.EXPOSE_UPSTREAM_ERROR,
        "log_response_preview_max": settings.LOG_RESPONSE_PREVIEW_MAX,
    }
    
    # Initialize and run the orchestrator
    from .services.chat_orchestrator import ChatOrchestrator
    orchestrator = ChatOrchestrator(
        memory_store=_MEMORY_STORE,
        session_cookie_settings=session_cookie_settings,
        memory_config=memory_config,
        aims_config=aims_config,
        vertex_config=vertex_config,
        debug_config=debug_config,
        logger=logger,
    )
    
    return await orchestrator.handle_chat(req, body)


@app.get("/config")
async def config():
    # Pull model preflight info if available
    mc = getattr(app.state, "model_check", {"available": "unknown"})
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
        "modelFallbacks": settings.MODEL_FALLBACKS,
        "modelAvailable": mc.get("available"),
        "modelCheck": mc,
        "autoContinueOnMaxTokens": settings.AUTO_CONTINUE_ON_MAX_TOKENS,
        "maxContinuations": settings.MAX_CONTINUATIONS,
        "suppressVertexAIDeprecation": settings.SUPPRESS_VERTEXAI_DEPRECATION,
        # Coaching toggles
        "aimsCoachingEnabled": settings.AIMS_COACHING_ENABLED,
        "aimsCoachingDefault": (os.getenv("AIMS_COACHING_DEFAULT", "false").lower() == "true"),
        # Reflect effective default here (Vertex client defaults to true now)
        "useVertexRest": os.getenv("USE_VERTEX_REST", "true").lower() == "true",
        "continueTailChars": int(os.getenv("CONTINUE_TAIL_CHARS", "500")),
        "continuationInstructionEnabled": os.getenv("CONTINUE_INSTRUCTION_ENABLED", "true").lower() == "true",
        "minContinueGrowth": int(os.getenv("MIN_CONTINUE_GROWTH", "10")),
        # Memory settings
        "memoryEnabled": settings.MEMORY_ENABLED,
        "memoryBackend": settings.MEMORY_BACKEND,
        "memoryMaxTurns": settings.MEMORY_MAX_TURNS,
        "memoryTtlSeconds": settings.MEMORY_TTL_SECONDS,
        "memoryStoreSize": len(_MEMORY_STORE),
        # Hard-coded defaults visibility
        "defaultCharacter": (DEFAULT_CHARACTER if settings.DEBUG_MODE and DEFAULT_CHARACTER else None),
        "defaultScene": (DEFAULT_SCENE if settings.DEBUG_MODE and DEFAULT_SCENE else None),
        # Session cookie diagnostics
        "sessionCookie": {
            "name": settings.SESSION_COOKIE_NAME,
            "secure": settings.SESSION_COOKIE_SECURE,
            "sameSite": settings.SESSION_COOKIE_SAMESITE,
            "maxAge": settings.SESSION_COOKIE_MAX_AGE,
        },
    }


@app.get("/modelcheck")
async def modelcheck():
    mc = getattr(app.state, "model_check", {"available": "unknown"})
    return {"modelId": settings.MODEL_ID, "region": settings.VERTEX_LOCATION, **mc}


@app.get("/diagnostics")
async def diagnostics():
    """Expose effective generation settings to help root-cause truncation issues."""
    use_rest = os.getenv("USE_VERTEX_REST", "true").lower() == "true"
    diag = {
        "transport": "rest" if use_rest else "sdk",
        "generationConfig": {
            "temperature": settings.TEMPERATURE,
            "maxOutputTokens": settings.MAX_TOKENS,
            "responseMimeType": "text/plain",
            # Note: We do not set "thinking" control in REST requests to maintain compatibility.
            "thinkingDisabled": None,
        },
        "autoContinueOnMaxTokens": settings.AUTO_CONTINUE_ON_MAX_TOKENS,
        "maxContinuations": settings.MAX_CONTINUATIONS,
        "continueTailChars": int(os.getenv("CONTINUE_TAIL_CHARS", "500")),
        "continuationInstructionEnabled": os.getenv("CONTINUE_INSTRUCTION_ENABLED", "true").lower() == "true",
        "minContinueGrowth": int(os.getenv("MIN_CONTINUE_GROWTH", "10")),
        "memory": {
            "enabled": settings.MEMORY_ENABLED,
            "backend": settings.MEMORY_BACKEND,
            "maxTurns": settings.MEMORY_MAX_TURNS,
            "ttlSeconds": settings.MEMORY_TTL_SECONDS,
            "storeSize": len(_MEMORY_STORE),
        },
    }
    return diag


@app.get("/models")
async def list_models(request: Request):
    """List available google/publisher models in this project+region using ADC.
    Returns a subset of fields for brevity.
    """
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    req_id = _get_request_id(request)
    started = time.time()
    try:
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = AuthorizedSession(creds)
        loc = settings.VERTEX_LOCATION
        host = "aiplatform.googleapis.com" if str(loc).lower() == "global" else f"{loc}-aiplatform.googleapis.com"
        url = f"https://{host}/v1/projects/{settings.PROJECT_ID}/locations/{loc}/publishers/google/models"
        r = session.get(url)
        latency_ms = int((time.time() - started) * 1000)
        if r.status_code != 200:
            logger.warning(json.dumps({
                "event": "models_list",
                "status": "error",
                "http": r.status_code,
                "requestId": req_id,
            }))
            return JSONResponse(status_code=502, content={
                "error": {
                    "message": f"Failed to list models (HTTP {r.status_code})",
                    "code": 502,
                    "requestId": req_id,
                }
            })
        data = r.json()
        models = data.get("models", [])
        # simplify
        out = [{
            "id": (m.get("name", "").split("/models/")[-1]),
            "displayName": m.get("displayName"),
            "supportedActions": m.get("supportedActions", {}),
        } for m in models]
        logger.info(json.dumps({
            "event": "models_list",
            "status": "ok",
            "latencyMs": latency_ms,
            "count": len(out),
            "requestId": req_id,
        }))
        return {"models": out, "count": len(out), "region": settings.VERTEX_LOCATION}
    except Exception as e:
        latency_ms = int((time.time() - started) * 1000)
        logger.exception("/models error: %s", e)
        logger.error(json.dumps({
            "event": "models_list",
            "status": "exception",
            "latencyMs": latency_ms,
            "error": str(e),
            "requestId": req_id,
        }))
        return JSONResponse(status_code=500, content={
            "error": {"message": "Internal server error", "code": 500, "requestId": req_id}
        })
