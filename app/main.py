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
from .persona import DEFAULT_CHARACTER, DEFAULT_SCENE

# Environment configuration with sensible defaults
PROJECT_ID = os.getenv("PROJECT_ID")
REGION = os.getenv("REGION", "us-central1")
# Use widely available defaults; override via env as needed
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.5-flash")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
# Increase default to allow longer responses; still configurable via env
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
model_fallbacks = os.getenv("MODEL_FALLBACKS", "gemini-2.5-flash-001").split(",")
MODEL_FALLBACKS = [m.strip() for m in model_fallbacks if m.strip()]
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()
LOG_REQUEST_BODY_MAX = int(os.getenv("LOG_REQUEST_BODY_MAX", "1024"))
LOG_HEADERS = os.getenv("LOG_HEADERS", "false").lower() == "true"
LOG_RESPONSE_PREVIEW_MAX = int(os.getenv("LOG_RESPONSE_PREVIEW_MAX", "512"))
EXPOSE_UPSTREAM_ERROR = os.getenv("EXPOSE_UPSTREAM_ERROR", "false").lower() == "true"
# Debug flag to control verbosity and revealing persona/scene in logs and UI
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
# Additional behavior flags
AUTO_CONTINUE_ON_MAX_TOKENS = os.getenv("AUTO_CONTINUE_ON_MAX_TOKENS", "true").lower() == "true"
MAX_CONTINUATIONS = int(os.getenv("MAX_CONTINUATIONS", "2"))
SUPPRESS_VERTEXAI_DEPRECATION = os.getenv("SUPPRESS_VERTEXAI_DEPRECATION", "true").lower() == "true"
# Memory configuration
MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "true").lower() == "true"
MEMORY_MAX_TURNS = int(os.getenv("MEMORY_MAX_TURNS", "8"))  # number of user/assistant turns to keep
MEMORY_TTL_SECONDS = int(os.getenv("MEMORY_TTL_SECONDS", "3600"))  # 1 hour
# Memory backend: "memory" (default) or "redis"
MEMORY_BACKEND = os.getenv("MEMORY_BACKEND", "memory").lower()
REDIS_URL = os.getenv("REDIS_URL")
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
REDIS_PREFIX = os.getenv("REDIS_PREFIX", "jaig:session:")

# Session cookie configuration
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "sessionId")
# Default secure true for production; allow override via env. In local dev over http, set to false.
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"
SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "lax")  # lax|strict|none
# Default max-age aligns with memory TTL if set, else 30 days
SESSION_COOKIE_MAX_AGE = int(os.getenv("SESSION_COOKIE_MAX_AGE", str(MEMORY_TTL_SECONDS if MEMORY_TTL_SECONDS > 0 else 30*24*60*60)))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("app")

app = FastAPI(title="Gemini Flash Demo", version="0.1.0")

# Memory store abstraction
class InMemoryStore:
    def __init__(self):
        self._store: dict[str, dict] = {}

    def get(self, key: str):
        return self._store.get(key)

    def __setitem__(self, key: str, value: dict):
        self._store[key] = value

    def items(self):
        return list(self._store.items())

    def pop(self, key: str, default=None):
        return self._store.pop(key, default)

    def __len__(self):
        return len(self._store)

class RedisStore:
    def __init__(self):
        try:
            import redis  # type: ignore
        except Exception as e:
            logger.warning("Redis not available (%s); falling back to in-memory store", e)
            raise
        # Create client
        if REDIS_URL:
            self.r = redis.from_url(REDIS_URL, decode_responses=True)
        else:
            self.r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD, decode_responses=True)
        # Test connection
        try:
            self.r.ping()
        except Exception as e:
            logger.warning("Cannot connect to Redis; falling back to in-memory store: %s", e)
            raise

    def _k(self, key: str) -> str:
        return f"{REDIS_PREFIX}{key}"

    def get(self, key: str):
        raw = self.r.get(self._k(key))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def __setitem__(self, key: str, value: dict):
        try:
            raw = json.dumps(value)
        except Exception:
            raw = "{}"
        pipe = self.r.pipeline()
        pipe.set(self._k(key), raw)
        if MEMORY_TTL_SECONDS > 0:
            pipe.expire(self._k(key), MEMORY_TTL_SECONDS)
        pipe.execute()

    def items(self):
        # Caution: SCAN to iterate keys; may be used rarely (prune/diagnostics)
        cursor = 0
        out = []
        pattern = f"{REDIS_PREFIX}*"
        while True:
            cursor, keys = self.r.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                vals = self.r.mget(keys)
                for k, v in zip(keys, vals):
                    if v:
                        try:
                            data = json.loads(v)
                        except Exception:
                            data = None
                        if data is not None:
                            sid = k[len(REDIS_PREFIX):]
                            out.append((sid, data))
            if cursor == 0:
                break
        return out

    def pop(self, key: str, default=None):
        val = self.get(key)
        self.r.delete(self._k(key))
        return val if val is not None else default

    def __len__(self):
        # Approximate size via SCAN cardinality
        count = 0
        cursor = 0
        pattern = f"{REDIS_PREFIX}*"
        while True:
            cursor, keys = self.r.scan(cursor=cursor, match=pattern, count=500)
            count += len(keys)
            if cursor == 0:
                break
        return count

# Instantiate store with fallback
try:
    if MEMORY_ENABLED and MEMORY_BACKEND == "redis":
        _MEMORY_STORE = RedisStore()
    else:
        _MEMORY_STORE = InMemoryStore()
except Exception:
    _MEMORY_STORE = InMemoryStore()
    MEMORY_BACKEND = "memory"

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
    body_preview = body_bytes[:LOG_REQUEST_BODY_MAX]
    body_logged = None
    if body_preview:
        try:
            body_logged = json.loads(body_preview.decode("utf-8"))
            # Redact persona/scene fields unless in debug mode
            if not DEBUG_MODE and isinstance(body_logged, dict):
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
    # Optional session support for server-side memory
    sessionId: Optional[str] = Field(default=None, description="Stable session identifier for conversation memory")
    # Optional persona/scene fields
    character: Optional[str] = Field(default=None, description="Persona/system prompt for the assistant (roleplay character)")
    scene: Optional[str] = Field(default=None, description="Scene objectives or context for this conversation")


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

    # Memory: prune expired sessions occasionally
    now = time.time()
    if MEMORY_ENABLED and _MEMORY_STORE and int(now) % 29 == 0:  # lightweight periodic prune
        try:
            expired = [sid for sid, v in _MEMORY_STORE.items() if (now - v.get("updated", now)) > MEMORY_TTL_SECONDS]
            for sid in expired:
                _MEMORY_STORE.pop(sid, None)
        except Exception:
            pass

    # Resolve session and persona/scene
    # Prefer body.sessionId, else cookie, else generate a new one and set cookie on response
    session_id = body.sessionId or req.cookies.get(SESSION_COOKIE_NAME)
    generated_session = False
    if not session_id:
        session_id = str(uuid.uuid4())
        generated_session = True
    character = body.character
    scene = body.scene

    # Initialize or update memory record
    mem = None
    if MEMORY_ENABLED and session_id:
        mem = _MEMORY_STORE.get(session_id)
        if not mem:
            mem = {"history": [], "character": None, "scene": None, "updated": now}
            _MEMORY_STORE[session_id] = mem
        # Update persona/scene if provided
        if character:
            mem["character"] = character.strip()
        if scene:
            mem["scene"] = scene.strip()
        mem["updated"] = now

    # Build system instruction
    system_instruction = None
    # Resolve effective persona/scene with fallback to hard-coded defaults
    effective_character = ((mem.get("character") if mem else None) or (character or None) or (DEFAULT_CHARACTER or None))
    effective_scene = ((mem.get("scene") if mem else None) or (scene or None) or (DEFAULT_SCENE or None))
    sys_parts = []
    if effective_character:
        sys_parts.append(f"You are roleplaying as: {effective_character}")
    if effective_scene:
        sys_parts.append(f"Scene objectives/context: {effective_scene}")
    if sys_parts:
        sys_parts.append("Stay consistent with the persona and scene throughout the conversation.")
        system_instruction = "\n".join(sys_parts)

    # Build prompt with recent history tail
    def _format_history(turns: list[dict]) -> str:
        lines = []
        for t in turns[-(MEMORY_MAX_TURNS*2):]:  # user+assistant pairs
            role = t.get("role")
            content = t.get("content") or ""
            if role == "user":
                lines.append(f"User: {content}")
            elif role == "assistant":
                lines.append(f"Assistant: {content}")
        return "\n".join(lines)

    if mem and mem.get("history"):
        history_text = _format_history(mem["history"]).strip()
        prompt_text = (
            ("Conversation so far:\n" + history_text + "\n\n") if history_text else ""
        ) + f"User: {body.message}\nAssistant:"
    else:
        prompt_text = body.message

    # Call Vertex AI
    started = time.time()

    def _attempt(model_id: str):
        client = VertexClient(project=PROJECT_ID, region=REGION, model_id=model_id)
        # Support both new and legacy VertexClient interfaces used in tests:
        # - New: generate_text(prompt=..., temperature=..., max_tokens=..., system_instruction=...) -> (text, meta)
        # - Legacy/mock: generate_text(prompt, temperature, max_tokens) -> text
        try:
            result = client.generate_text(
                prompt=prompt_text,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                system_instruction=system_instruction,
            )
        except TypeError:
            # Fallback for mocks that don't accept system_instruction or keyword args
            result = client.generate_text(prompt_text, TEMPERATURE, MAX_TOKENS)
        # Normalize return shape
        if isinstance(result, tuple) and len(result) == 2:
            text, meta = result
        else:
            text = str(result)
            meta = {
                "finishReason": None,
                "promptTokens": None,
                "candidatesTokens": None,
                "totalTokens": None,
                "thoughtsTokens": None,
                "safety": [],
                "textLen": len((text or "").strip()),
                "transport": None,
                "continuationCount": 0,
                "noProgressBreak": None,
                "continueTailChars": None,
                "continuationInstructionEnabled": None,
            }
        return text, meta

    try:
        # First attempt with configured MODEL_ID
        reply, meta = _attempt(MODEL_ID)
        latency_ms = int((time.time() - started) * 1000)
        preview = None
        try:
            preview = (reply or "")[:LOG_RESPONSE_PREVIEW_MAX]
        except Exception:
            preview = None
        logger.info(
            json.dumps(
                {
                    "event": "chat",
                    "status": "ok",
                    "latencyMs": latency_ms,
                    "modelId": MODEL_ID,
                    "requestId": _get_request_id(req),
                    "sessionId": session_id,
                    "finishReason": meta.get("finishReason"),
                    "textLen": meta.get("textLen"),
                    "tokens": {
                        "prompt": meta.get("promptTokens"),
                        "candidates": meta.get("candidatesTokens"),
                        "total": meta.get("totalTokens"),
                        "thoughts": meta.get("thoughtsTokens"),
                    },
                    "reply": reply,
                    "replyPreview": preview,
                    "continuationCount": meta.get("continuationCount"),
                    "transport": meta.get("transport"),
                    "noProgressBreak": meta.get("noProgressBreak"),
                    "continueTailChars": meta.get("continueTailChars"),
                    "continuationInstructionEnabled": meta.get("continuationInstructionEnabled"),
                }
            )
        )
        # Persist to memory after success
        if MEMORY_ENABLED and session_id:
            try:
                mem = _MEMORY_STORE.get(session_id) or {"history": [], "character": None, "scene": None, "updated": time.time()}
                # Append user and assistant turns
                mem.setdefault("history", []).append({"role": "user", "content": body.message})
                mem["history"].append({"role": "assistant", "content": reply})
                # Trim to last N turns (user+assistant pairs)
                max_items = MEMORY_MAX_TURNS * 2
                if len(mem["history"]) > max_items:
                    mem["history"] = mem["history"][-max_items:]
                mem["updated"] = time.time()
                _MEMORY_STORE[session_id] = mem
            except Exception:
                logger.debug("Memory persistence failed for session %s", session_id)
        resp = JSONResponse(status_code=200, content={"reply": reply, "model": MODEL_ID, "latencyMs": latency_ms})
        try:
            resp.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=session_id,
                max_age=SESSION_COOKIE_MAX_AGE,
                httponly=True,
                secure=SESSION_COOKIE_SECURE,
                samesite=SESSION_COOKIE_SAMESITE,
                path="/",
            )
        except Exception:
            pass
        return resp
    except VertexAIError as e:
        # If model not found and fallbacks configured, try them sequentially
        if getattr(e, "status_code", None) == 404 and MODEL_FALLBACKS:
            fallback_errors = []
            for fb in MODEL_FALLBACKS:
                try:
                    reply, meta = _attempt(fb)
                    latency_ms = int((time.time() - started) * 1000)
                    preview = None
                    try:
                        preview = (reply or "")[:LOG_RESPONSE_PREVIEW_MAX]
                    except Exception:
                        preview = None
                    logger.warning(
                        json.dumps(
                            {
                                "event": "chat_fallback",
                                "status": "ok",
                                "latencyMs": latency_ms,
                                "modelId": fb,
                                "originalModelId": MODEL_ID,
                                "requestId": _get_request_id(req),
                                "sessionId": session_id,
                                "finishReason": meta.get("finishReason"),
                                "textLen": meta.get("textLen"),
                                "tokens": {
                                    "prompt": meta.get("promptTokens"),
                                    "candidates": meta.get("candidatesTokens"),
                                    "total": meta.get("totalTokens"),
                                    "thoughts": meta.get("thoughtsTokens"),
                                },
                                "reply": reply,
                                "replyPreview": preview,
                                "continuationCount": meta.get("continuationCount"),
                                "transport": meta.get("transport"),
                                "noProgressBreak": meta.get("noProgressBreak"),
                                "continueTailChars": meta.get("continueTailChars"),
                                "continuationInstructionEnabled": meta.get("continuationInstructionEnabled"),
                            }
                        )
                    )
                    # Persist to memory after fallback success
                    if MEMORY_ENABLED and session_id:
                        try:
                            mem = _MEMORY_STORE.get(session_id) or {"history": [], "character": None, "scene": None, "updated": time.time()}
                            mem.setdefault("history", []).append({"role": "user", "content": body.message})
                            mem["history"].append({"role": "assistant", "content": reply})
                            max_items = MEMORY_MAX_TURNS * 2
                            if len(mem["history"]) > max_items:
                                mem["history"] = mem["history"][-max_items:]
                            mem["updated"] = time.time()
                            _MEMORY_STORE[session_id] = mem
                        except Exception:
                            logger.debug("Memory persistence failed for session %s", session_id)
                    resp = JSONResponse(status_code=200, content={"reply": reply, "model": fb, "latencyMs": latency_ms})
                    try:
                        resp.set_cookie(
                            key=SESSION_COOKIE_NAME,
                            value=session_id,
                            max_age=SESSION_COOKIE_MAX_AGE,
                            httponly=True,
                            secure=SESSION_COOKIE_SECURE,
                            samesite=SESSION_COOKIE_SAMESITE,
                            path="/",
                        )
                    except Exception:
                        pass
                    return resp
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
            resp = JSONResponse(status_code=404, content=payload)
            try:
                resp.set_cookie(
                    key=SESSION_COOKIE_NAME,
                    value=session_id,
                    max_age=SESSION_COOKIE_MAX_AGE,
                    httponly=True,
                    secure=SESSION_COOKIE_SECURE,
                    samesite=SESSION_COOKIE_SAMESITE,
                    path="/",
                )
            except Exception:
                pass
            return resp

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
        resp = JSONResponse(status_code=502, content=payload)
        try:
            resp.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=session_id,
                max_age=SESSION_COOKIE_MAX_AGE,
                httponly=True,
                secure=SESSION_COOKIE_SECURE,
                samesite=SESSION_COOKIE_SAMESITE,
                path="/",
            )
        except Exception:
            pass
        return resp
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
        resp = JSONResponse(
            status_code=500,
            content={"error": {"message": "Internal server error", "code": 500, "requestId": _get_request_id(req)}},
        )
        try:
            resp.set_cookie(
                key=SESSION_COOKIE_NAME,
                value=session_id,
                max_age=SESSION_COOKIE_MAX_AGE,
                httponly=True,
                secure=SESSION_COOKIE_SECURE,
                samesite=SESSION_COOKIE_SAMESITE,
                path="/",
            )
        except Exception:
            pass
        return resp


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
        "logResponsePreviewMax": LOG_RESPONSE_PREVIEW_MAX,
        "allowedOrigins": ALLOWED_ORIGINS,
        "exposeUpstreamError": EXPOSE_UPSTREAM_ERROR,
        "debugMode": DEBUG_MODE,
        "modelFallbacks": MODEL_FALLBACKS,
        "autoContinueOnMaxTokens": AUTO_CONTINUE_ON_MAX_TOKENS,
        "maxContinuations": MAX_CONTINUATIONS,
        "suppressVertexAIDeprecation": SUPPRESS_VERTEXAI_DEPRECATION,
        # Reflect effective default here (Vertex client defaults to true now)
        "useVertexRest": os.getenv("USE_VERTEX_REST", "true").lower() == "true",
        "continueTailChars": int(os.getenv("CONTINUE_TAIL_CHARS", "500")),
        "continuationInstructionEnabled": os.getenv("CONTINUE_INSTRUCTION_ENABLED", "true").lower() == "true",
        "minContinueGrowth": int(os.getenv("MIN_CONTINUE_GROWTH", "10")),
        # Memory settings
        "memoryEnabled": MEMORY_ENABLED,
        "memoryBackend": MEMORY_BACKEND,
        "memoryMaxTurns": MEMORY_MAX_TURNS,
        "memoryTtlSeconds": MEMORY_TTL_SECONDS,
        "memoryStoreSize": len(_MEMORY_STORE),
        # Hard-coded defaults visibility
        "defaultCharacter": (DEFAULT_CHARACTER if DEBUG_MODE and DEFAULT_CHARACTER else None),
        "defaultScene": (DEFAULT_SCENE if DEBUG_MODE and DEFAULT_SCENE else None),
        # Session cookie diagnostics
        "sessionCookie": {
            "name": SESSION_COOKIE_NAME,
            "secure": SESSION_COOKIE_SECURE,
            "sameSite": SESSION_COOKIE_SAMESITE,
            "maxAge": SESSION_COOKIE_MAX_AGE,
        },
    }


@app.get("/diagnostics")
async def diagnostics():
    """Expose effective generation settings to help root-cause truncation issues."""
    use_rest = os.getenv("USE_VERTEX_REST", "true").lower() == "true"
    diag = {
        "transport": "rest" if use_rest else "sdk",
        "generationConfig": {
            "temperature": TEMPERATURE,
            "maxOutputTokens": MAX_TOKENS,
            "responseMimeType": "text/plain",
            # Note: We do not set "thinking" control in REST requests to maintain compatibility.
            "thinkingDisabled": None,
        },
        "autoContinueOnMaxTokens": AUTO_CONTINUE_ON_MAX_TOKENS,
        "maxContinuations": MAX_CONTINUATIONS,
        "continueTailChars": int(os.getenv("CONTINUE_TAIL_CHARS", "500")),
        "continuationInstructionEnabled": os.getenv("CONTINUE_INSTRUCTION_ENABLED", "true").lower() == "true",
        "minContinueGrowth": int(os.getenv("MIN_CONTINUE_GROWTH", "10")),
        "memory": {
            "enabled": MEMORY_ENABLED,
            "backend": MEMORY_BACKEND,
            "maxTurns": MEMORY_MAX_TURNS,
            "ttlSeconds": MEMORY_TTL_SECONDS,
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
