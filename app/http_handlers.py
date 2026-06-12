from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

module_logger = logging.getLogger(__name__)


def get_request_id(request: Request) -> Optional[str]:
    header = request.headers.get("x-cloud-trace-context") or request.headers.get("x-request-id")
    if header:
        return header
    # noinspection PyBroadException
    try:
        return getattr(request.state, "request_id", None) or str(uuid.uuid4())
    except Exception:
        # Fallback for when request.state is not available or corrupted
        return str(uuid.uuid4())


def _extract_session_id(*, request: Request, body_logged: Any = None) -> Optional[str]:
    try:
        state_session_id = getattr(request.state, "session_id", None)
        if state_session_id:
            return str(state_session_id)
    except Exception:
        pass

    try:
        query_session_id = request.query_params.get("sessionId")
        if query_session_id:
            return query_session_id
    except Exception:
        pass

    if isinstance(body_logged, dict):
        raw = body_logged.get("sessionId")
        if raw:
            return str(raw)

    return None


def install_http_handlers(app: FastAPI, *, settings: Any, logger: logging.Logger) -> None:
    # Use the provided logger for request/response logging
    # We rename it to avoid conflict with module-level logger if needed,
    # but nested functions will prefer the local one.
    @app.exception_handler(HTTPException)
    async def on_http_exception(request: Request, exc: HTTPException):
        req_id = get_request_id(request)
        session_id = _extract_session_id(request=request)
        logger.warning(json.dumps({
            "event": "http_exception",
            "status": exc.status_code,
            "detail": exc.detail,
            "requestId": req_id,
            "sessionId": session_id,
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
        body_logged = await _request_body_for_log(request)
        session_id = _extract_session_id(request=request, body_logged=body_logged)
        errors = json.loads(json.dumps(exc.errors(), default=str))

        logger.warning(json.dumps({
            "event": "request_validation_error",
            "errors": errors,
            "body": body_logged,
            "requestId": req_id,
            "sessionId": session_id,
            "path": request.url.path,
            "method": request.method,
        }))
        return JSONResponse(status_code=422, content={
            "error": {"message": "Request validation failed", "code": 422, "requestId": req_id, "errors": errors}
        })

    @app.exception_handler(Exception)
    async def on_unhandled_exception(request: Request, exc: Exception):
        req_id = get_request_id(request)
        session_id = _extract_session_id(request=request)
        logger.exception("Unhandled application exception: %s", exc)
        logger.error(json.dumps({
            "event": "unhandled_exception",
            "error": str(exc),
            "requestId": req_id,
            "sessionId": session_id,
            "path": request.url.path,
            "method": request.method,
        }))
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
        body_bytes = await _read_body(request)

        async def receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        try:
            request._receive = receive  # type: ignore[attr-defined]
        except Exception as e:
            logger.debug("Failed to patch request._receive: %s", e)
            pass

        client_host = request.client.host if request.client is not None else None
        body_logged = _body_preview_for_log(body_bytes, settings=settings)
        session_id = _extract_session_id(request=request, body_logged=body_logged)
        request.state.session_id = session_id
        logger.info(json.dumps({
            "event": "request_start",
            "method": request.method,
            "path": request.url.path,
            "client": client_host,
            "requestId": req_id,
            "sessionId": session_id,
            "bodySize": len(body_bytes) if body_bytes else 0,
            "body": body_logged,
            "headers": _headers_for_log(request, settings=settings),
        }))

        try:
            response = await call_next(request)
        except Exception as exc:
            latency_ms = int((time.time() - start) * 1000)
            logger.exception("Unhandled exception processing request: %s", exc)
            logger.error(json.dumps({
                "event": "request_error",
                "requestId": req_id,
                "sessionId": session_id,
                "latencyMs": latency_ms,
                "error": str(exc),
            }))
            raise

        try:
            response.headers["x-request-id"] = req_id
        except Exception as e:
            logger.debug("Failed to set x-request-id header: %s", e)
            pass

        _log_request_end(logger, request=request, response=response, req_id=req_id, start=start)
        return response


async def _request_body_for_log(request: Request) -> Any:
    body_logged = None
    if request.method in ("POST", "PUT", "PATCH"):
        raw = await _read_body(request)
        if raw:
            try:
                body_logged = json.loads(raw.decode("utf-8"))
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
        body_logged = json.loads(body_preview.decode("utf-8"))
        if not settings.DEBUG_MODE and isinstance(body_logged, dict):
            if "character" in body_logged:
                body_logged["character"] = "<hidden>"
            if "scene" in body_logged:
                body_logged["scene"] = "<hidden>"
        return body_logged
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
        "sessionId": _extract_session_id(request=request),
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
