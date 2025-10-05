import json
import logging
import os
import time
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .vertex import VertexClient, VertexAIError

# Environment configuration with sensible defaults
PROJECT_ID = os.getenv("PROJECT_ID")
REGION = os.getenv("REGION", "us-central1")
# Use widely available defaults; override via env as needed
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.5-flash")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1024"))
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
model_fallbacks = os.getenv("MODEL_FALLBACKS", "gemini-2.5-flash-001").split(",")
MODEL_FALLBACKS = [m.strip() for m in model_fallbacks if m.strip()]
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
LOG_REQUEST_BODY_MAX = int(os.getenv("LOG_REQUEST_BODY_MAX", "1024"))
LOG_HEADERS = os.getenv("LOG_HEADERS", "false").lower() == "true"
EXPOSE_UPSTREAM_ERROR = os.getenv("EXPOSE_UPSTREAM_ERROR", "false").lower() == "true"

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("app")

app = FastAPI(title="Gemini Flash Demo", version="0.1.0")

# Optional CORS
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["POST", "OPTIONS"],
        allow_headers=["Content-Type"],
        max_age=3600,
    )



# Exception handlers to surface better errors with request correlation
@app.exception_handler(HTTPException)
async def on_http_exception(request: Request, exc: HTTPException):
    # Let FastAPI build the default response content, but add requestId and log
    req_id = _get_request_id(request)
    logger.warning(json.dumps({
        "event": "http_exception",
        "status": exc.status_code,
        "detail": exc.detail,
        "requestId": req_id,
        "path": request.url.path,
        "method": request.method,
    }))
    # Ensure detail is JSON-like
    detail = exc.detail if isinstance(exc.detail, (dict, list)) else {"message": str(exc.detail)}
    detail.setdefault("requestId", req_id)
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    req_id = _get_request_id(request)
    logger.warning(json.dumps({
        "event": "request_validation_error",
        "errors": exc.errors(),
        "body": await request.body() if request.method in ("POST", "PUT", "PATCH") else None,
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
    body_preview = body_bytes[:LOG_REQUEST_BODY_MAX]
    body_logged = None
    if body_preview:
        try:
            body_logged = json.loads(body_preview.decode("utf-8"))
        except Exception:
            # fallback to string preview
            try:
                body_logged = body_preview.decode("utf-8", errors="replace")
            except Exception:
                body_logged = "<binary>"

    headers_logged = None
    if LOG_HEADERS:
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


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, description="User input message")


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
    if PROJECT_ID is None:
        raise HTTPException(status_code=500, detail={"error": {"message": "PROJECT_ID not set", "code": 500}})

    # Validate size limit 2 KiB
    try:
        encoded = body.message.encode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail={"error": {"message": "Invalid UTF-8 in message", "code": 400}})

    if len(encoded) > 2048:
        raise HTTPException(status_code=400,
                            detail={"error": {"message": "Message too large (max 2 KiB)", "code": 400}})

    # Call Vertex AI
    started = time.time()

    def _attempt(model_id: str):
        client = VertexClient(project=PROJECT_ID, region=REGION, model_id=model_id)
        return client.generate_text(
            prompt=body.message,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )

    try:
        # First attempt with configured MODEL_ID
        reply = _attempt(MODEL_ID)
        latency_ms = int((time.time() - started) * 1000)
        logger.info(
            json.dumps(
                {
                    "event": "chat",
                    "status": "ok",
                    "latencyMs": latency_ms,
                    "modelId": MODEL_ID,
                    "requestId": _get_request_id(req),
                }
            )
        )
        return {"reply": reply, "model": MODEL_ID, "latencyMs": latency_ms}
    except VertexAIError as e:
        # If model not found and fallbacks configured, try them sequentially
        if getattr(e, "status_code", None) == 404 and MODEL_FALLBACKS:
            fallback_errors = []
            for fb in MODEL_FALLBACKS:
                try:
                    reply = _attempt(fb)
                    latency_ms = int((time.time() - started) * 1000)
                    logger.warning(
                        json.dumps(
                            {
                                "event": "chat_fallback",
                                "status": "ok",
                                "latencyMs": latency_ms,
                                "modelId": fb,
                                "originalModelId": MODEL_ID,
                                "requestId": _get_request_id(req),
                            }
                        )
                    )
                    return {"reply": reply, "model": fb, "latencyMs": latency_ms}
                except VertexAIError as fe:
                    fallback_errors.append(str(fe))
                    logger.warning(
                        json.dumps(
                            {
                                "event": "chat_fallback_attempt",
                                "status": "failed",
                                "modelId": fb,
                                "originalModelId": MODEL_ID,
                                "requestId": _get_request_id(req),
                                "error": str(fe),
                            }
                        )
                    )
            # All fallbacks failed; proceed to map as 404 below

        latency_ms = int((time.time() - started) * 1000)
        # Map 404 Not Found distinctly for clearer client-side action
        if getattr(e, "status_code", None) == 404:
            logger.error(
                json.dumps(
                    {
                        "event": "chat",
                        "status": "model_not_found",
                        "latencyMs": latency_ms,
                        "modelId": MODEL_ID,
                        "requestId": _get_request_id(req),
                        "error": str(e),
                    }
                )
            )
            req_id = _get_request_id(req)
            guidance = (
                "Publisher model not found or access denied. Verify MODEL_ID and REGION; ensure Vertex AI API is enabled, "
                "billing is active, and your ADC principal has roles/aiplatform.user in the project. You may set MODEL_FALLBACKS "
                "(comma-separated) to try alternative model IDs like 'gemini-2.5-flash' or 'gemini-2.5-flash-001'."
            )
            payload = {"error": {"message": guidance, "code": 404, "requestId": req_id}}
            if EXPOSE_UPSTREAM_ERROR:
                payload["error"]["upstream"] = str(e)
            return JSONResponse(status_code=404, content=payload)

        # Default: treat as upstream 502
        logger.error(
            json.dumps(
                {
                    "event": "chat",
                    "status": "upstream_error",
                    "latencyMs": latency_ms,
                    "modelId": MODEL_ID,
                    "requestId": _get_request_id(req),
                    "error": str(e),
                }
            )
        )
        req_id = _get_request_id(req)
        payload = {"error": {"message": "Upstream error calling Vertex AI", "code": 502, "requestId": req_id}}
        if EXPOSE_UPSTREAM_ERROR:
            payload["error"]["upstream"] = str(e)
        return JSONResponse(status_code=502, content=payload)
    except Exception as e:
        latency_ms = int((time.time() - started) * 1000)
        logger.exception("Unexpected error: %s", e)
        logger.error(
            json.dumps(
                {
                    "event": "chat",
                    "status": "unexpected_error",
                    "latencyMs": latency_ms,
                    "modelId": MODEL_ID,
                    "requestId": _get_request_id(req),
                    "error": str(e),
                }
            )
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Internal server error", "code": 500, "requestId": _get_request_id(req)}},
        )


@app.get("/config")
async def config():
    return {
        "projectId": PROJECT_ID,
        "region": REGION,
        "modelId": MODEL_ID,
        "temperature": TEMPERATURE,
        "maxTokens": MAX_TOKENS,
        "logLevel": LOG_LEVEL,
        "logHeaders": LOG_HEADERS,
        "logRequestBodyMax": LOG_REQUEST_BODY_MAX,
        "allowedOrigins": ALLOWED_ORIGINS,
        "exposeUpstreamError": EXPOSE_UPSTREAM_ERROR,
        "modelFallbacks": MODEL_FALLBACKS,
    }


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
        url = f"https://{REGION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{REGION}/publishers/google/models"
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
        return {"models": out, "count": len(out), "region": REGION}
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
