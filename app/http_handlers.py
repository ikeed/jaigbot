from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

module_logger = logging.getLogger(__name__)


def get_request_id(request: Request) -> str | None:
    header = request.headers.get("x-cloud-trace-context") or request.headers.get("x-request-id")
    if header:
        return header
    # noinspection PyBroadException
    try:
        return getattr(request.state, "request_id", None) or str(uuid.uuid4())
    except Exception:
        # Fallback for when request.state is not available or corrupted
        return str(uuid.uuid4())


def install_http_handlers(app: FastAPI, *, settings: Any, logger: logging.Logger) -> None:
    # Use the provided logger for request/response logging
    # We rename it to avoid conflict with module-level logger if needed,
    # but nested functions will prefer the local one.
    @app.exception_handler(HTTPException)
    async def on_http_exception(request: Request, exc: HTTPException):
        req_id = get_request_id(request)
        logger.warning(json.dumps({
            "event": "http_exception",
            "status": exc.status_code,
            "detail": exc.detail,
            "requestId": req_id,
            "path": request.url.path,
            "method": request.method,
        }))

        base: dict[str, Any]
        if isinstance(exc.detail, dict):
            error_detail = exc.detail.get("error", exc.detail)
            base = error_detail.copy() if isinstance(error_detail, dict) else {"message": str(error_detail)}
        elif isinstance(exc.detail, list):
            base = {"errors": exc.detail}
        else:
            base = {"message": str(exc.detail)}

        base.setdefault("message", "")
        base.setdefault("code", exc.status_code)
        base.setdefault("requestId", req_id)

        return JSONResponse(status_code=exc.status_code, content={"error": base})

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        req_id = get_request_id(request)
        body_logged = await _request_body_for_log(request, settings=settings)

        logger.warning(json.dumps({
            "event": "request_validation_error",
            "errors": exc.errors(),
            "body": body_logged,
            "requestId": req_id,
            "path": request.url.path,
            "method": request.method,
        }))
        return JSONResponse(status_code=422, content={
            "error": {"message": "Request validation failed", "code": 422, "requestId": req_id, "errors": exc.errors()}
        })

    @app.exception_handler(Exception)
    async def on_unhandled_exception(request: Request, exc: Exception):
        req_id = get_request_id(request)
        # One structured log line per error; exc_info carries the traceback
        # instead of a second, separately-formatted logger.exception() line.
        logger.error(json.dumps({
            "event": "unhandled_exception",
            "error": str(exc),
            "requestId": req_id,
            "path": request.url.path,
            "method": request.method,
        }), exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Internal server error", "code": 500, "requestId": req_id}},
        )

    # noinspection PyUnresolvedReferences
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        req_id = request.headers.get("x-cloud-trace-context") or request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = req_id

        start = time.time()
        # Reading the body here is safe for downstream handlers: Starlette's
        # BaseHTTPMiddleware wraps this request in a _CachedRequest whose
        # wrapped_receive replays the cached body to the downstream app once
        # .body() has been called in a dispatch function.
        body_bytes = await _read_body(request)

        client_host = request.client.host if request.client is not None else None
        logger.info(json.dumps({
            "event": "request_start",
            "method": request.method,
            "path": request.url.path,
            "client": client_host,
            "requestId": req_id,
            "bodySize": len(body_bytes) if body_bytes else 0,
            "body": _body_preview_for_log(body_bytes, settings=settings),
            "headers": _headers_for_log(request, settings=settings),
        }))

        try:
            response = await call_next(request)
        except Exception as exc:
            latency_ms = int((time.time() - start) * 1000)
            logger.error(json.dumps({
                "event": "request_error",
                "requestId": req_id,
                "latencyMs": latency_ms,
                "error": str(exc),
            }), exc_info=True)
            raise

        try:
            response.headers["x-request-id"] = req_id
        except Exception as e:
            logger.debug("Failed to set x-request-id header: %s", e)
            pass

        _log_request_end(logger, request=request, response=response, req_id=req_id, start=start)
        return response


# Request-body fields hidden from logs unless DEBUG_MODE -- per CLAUDE.md,
# never log persona prompts, scene text, or the clinician's actual message.
_REDACTED_BODY_FIELDS = ("character", "scene", "message")


def _redact_body_fields(body: Any, *, settings: Any) -> Any:
    if not settings.DEBUG_MODE and isinstance(body, dict):
        for field in _REDACTED_BODY_FIELDS:
            if field in body:
                body[field] = "<hidden>"
    return body


async def _request_body_for_log(request: Request, *, settings: Any) -> Any:
    body_logged = None
    if request.method in ("POST", "PUT", "PATCH"):
        raw = await _read_body(request)
        if raw:
            try:
                body_logged = _redact_body_fields(json.loads(raw.decode("utf-8")), settings=settings)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                module_logger.debug("Failed to decode request body as JSON: %s", e)
                try:
                    body_logged = raw.decode("utf-8", errors="replace")
                except Exception as e:
                    module_logger.debug("Failed to decode request body as UTF-8: %s", e)
                    body_logged = "<binary>"
    return body_logged


async def _read_body(request: Request) -> bytes:
    try:
        return await request.body()
    except Exception as e:
        module_logger.warning("Failed to read request body: %s", e)
        return b""


def _body_preview_for_log(body_bytes: bytes, *, settings: Any) -> Any:
    body_preview = body_bytes[:settings.LOG_REQUEST_BODY_MAX]
    if not body_preview:
        return None
    try:
        return _redact_body_fields(json.loads(body_preview.decode("utf-8")), settings=settings)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        module_logger.debug("Failed to decode body preview as JSON: %s", e)
        try:
            return body_preview.decode("utf-8", errors="replace")
        except Exception as e:
            module_logger.debug("Failed to decode body preview as UTF-8: %s", e)
            return "<binary>"


def _headers_for_log(request: Request, *, settings: Any) -> dict | None:
    if not settings.LOG_HEADERS:
        return None
    redact = {"authorization", "cookie", "set-cookie"}
    return {key: ("<redacted>" if key.lower() in redact else value) for key, value in request.headers.items()}


def _log_request_end(
    logger: logging.Logger,
    *,
    request: Request,
    response: Any,
    req_id: str,
    start: float,
) -> None:
    latency_ms = int((time.time() - start) * 1000)
    status_code = getattr(response, "status_code", None)
    end_event = json.dumps({
        "event": "request_end",
        "method": request.method,
        "path": request.url.path,
        "status": status_code,
        "latencyMs": latency_ms,
        "requestId": req_id,
    })
    try:
        if isinstance(status_code, int) and status_code >= 500:
            logger.error(end_event)
        elif isinstance(status_code, int) and status_code >= 400:
            logger.warning(end_event)
        else:
            logger.info(end_event)
    except Exception as e:
        logger.debug("Failed to log request end: %s", e)
        logger.info(end_event)
