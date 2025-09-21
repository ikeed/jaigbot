import json
import logging
import os
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .vertex import VertexClient, VertexAIError

# Environment configuration with sensible defaults
PROJECT_ID = os.getenv("PROJECT_ID")
REGION = os.getenv("REGION", "us-central1")
MODEL_ID = os.getenv("MODEL_ID", "gemini-1.5-flash-002")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "256"))
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
LOG_LEVEL = os.getenv("LOG_LEVEL", "info").upper()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
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

# Static files and root route
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    index_path = os.path.join(static_dir, "index.html")
    return FileResponse(index_path)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, description="User input message")


def _get_request_id(request: Request) -> Optional[str]:
    # X-Cloud-Trace-Context: traceId/spanId;o=traceTrue
    h = request.headers.get("x-cloud-trace-context") or request.headers.get("x-request-id")
    return h


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
        raise HTTPException(status_code=400, detail={"error": {"message": "Message too large (max 2 KiB)", "code": 400}})

    # Call Vertex AI
    started = time.time()
    vc = VertexClient(project=PROJECT_ID, region=REGION, model_id=MODEL_ID)
    try:
        reply = vc.generate_text(
            prompt=body.message,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
        latency_ms = int((time.time() - started) * 1000)
        # Structured log
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
        latency_ms = int((time.time() - started) * 1000)
        logger.warning(
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
        return JSONResponse(
            status_code=502,
            content={"error": {"message": "Upstream error calling Vertex AI", "code": 502}},
        )
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
                }
            )
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Internal server error", "code": 500}},
        )
