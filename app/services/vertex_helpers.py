import contextvars
import json
import logging
import re
from typing import Any

from ..vertex import VertexAIError, VertexClient

_logger = logging.getLogger(__name__)

# Track the model that produced the most recent response, per async task.
# Using ContextVar instead of a module-level global avoids race conditions
# when multiple requests are handled concurrently in the same event loop.
_last_model_used_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_last_model_used", default=None
)


def get_last_model_used() -> str | None:
    return _last_model_used_var.get()


def _coerce_json_object(value: Any) -> dict[Any, Any] | None:
    return value if isinstance(value, dict) else None


def _extract_json_payload(text: str) -> dict[Any, Any] | None:
    """Extract a JSON value from a model response without manual brace scanning.

    Strategy (stable and maintainable):
    1) Prefer fenced code blocks labeled as JSON: ```json ... ``` (case-insensitive).
       Try each block body with json.loads in order. If none parse, try unlabeled fences.
    2) Minimal cleanup fallback: strip raw fence markers/backticks and attempt a single
       json.loads on the entire cleaned string.

    Returns a Python object (dict/list/str/number/bool/null) or None.
    """
    if not text:
        return None

    s = text.strip()

    # 1) Extract from fenced ```json blocks first (prefer explicit json/json5)
    FENCE_RE = re.compile(r"```\s*(json5?|json)?\s*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)
    matches = FENCE_RE.findall(s)
    # First pass: explicitly labeled json/json5
    for lang, body in matches:
        if lang and lang.lower() not in {"json", "json5"}:
            continue
        try:
            return _coerce_json_object(json.loads(body))
        except Exception as e:
            _logger.debug("Failed to extract JSON from labeled block: %s", e)
            pass
    # Second pass: unlabeled fences
    for _, body in matches:
        try:
            return _coerce_json_object(json.loads(body))
        except Exception as e:
            _logger.debug("Failed to extract JSON from unlabeled block: %s", e)
            pass

    # 2) Minimal cleanup fallback: remove raw fence markers/backticks and try once
    cleaned = s.replace("```", "").strip()
    try:
        return _coerce_json_object(json.loads(cleaned))
    except Exception as e:
        _logger.debug("Failed to extract JSON from cleaned text: %s", e)
        return None


def _maybe_extract_patient_reply(obj: dict | None) -> str | None:
    """If obj looks like our REPLY_SCHEMA, return the patient_reply string."""
    if isinstance(obj, dict):
        val = obj.get("patient_reply")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def vertex_call_with_fallback_text(
    *,
    project: str,
    region: str,
    primary_model: str,
    fallbacks: list[str],
    temperature: float,
    max_tokens: int,
    prompt: str,
    system_instruction: str | None,
    log_path: str,
    logger,
    client_cls: type = VertexClient,
) -> str:
    """Generate a text response using Vertex with model fallback logging.

    Preserves the same event shape used by existing logs. Tries JSON schema path first
    (reply schema embedded via gateway) and falls back to plain text generation when
    unsupported.
    """
    from .vertex_gateway import VertexGateway

    models_to_try = [primary_model] + [m for m in fallbacks if m and m != primary_model]
    tried: list[str] = []

    def _on_fallback(failed_mid: str):
        tried.append(failed_mid)
        next_model = models_to_try[len(tried):][:1] or None
        logger.info(
            json.dumps(
                {
                    "event": "vertex_model_fallback",
                    "path": log_path,
                    "failedModel": failed_mid,
                    "next": next_model,
                }
            )
        )

    gateway = VertexGateway(
        project=project,
        region=region,
        primary_model=primary_model,
        fallbacks=fallbacks,
        temperature=temperature,
        max_tokens=max_tokens,
        client_cls=client_cls,
    )

    def _record_model():
        _last_model_used_var.set(getattr(gateway, "last_model_used", primary_model))

    # Prefer JSON path if supported, else non-JSON fallback
    try:
        from ..json_schemas import REPLY_SCHEMA

        result = gateway.generate_text_json(
            prompt=prompt,
            response_schema=REPLY_SCHEMA,
            system_instruction=system_instruction,
            log_fallback=_on_fallback,
        )
        obj = _extract_json_payload(result)
        reply = _maybe_extract_patient_reply(obj)
        if reply:
            _record_model()
            path = (log_path or "").lower()
            if "legacy" in path:
                return reply
            return json.dumps({"patient_reply": reply}, separators=(",", ":"))
        _record_model()
        try:
            path = (log_path or "").lower()
            if "legacy" in path and ("```" in result or "json" in (result or "").lower()):
                plain = gateway.generate_text(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    log_fallback=_on_fallback,
                )
                return plain
            return result
        except Exception as e:
            _logger.warning("Secondary generate_text call failed for legacy path: %s", e)
            return result
    except VertexAIError:
        raise
    except Exception as e:
        _logger.error("Primary vertex call failed: %s", e)
        result = gateway.generate_text(
            prompt=prompt,
            system_instruction=system_instruction,
            log_fallback=_on_fallback,
        )
        _record_model()
        return result


async def avertex_call_with_fallback_text(
    *,
    project: str,
    region: str,
    primary_model: str,
    fallbacks: list[str],
    temperature: float,
    max_tokens: int,
    prompt: str,
    system_instruction: str | None,
    log_path: str,
    logger,
    client_cls: type = VertexClient,
) -> str:
    """Async variant of vertex_call_with_fallback_text.

    Uses native async gateway calls instead of blocking threads.
    """
    from .vertex_gateway import VertexGateway

    models_to_try = [primary_model] + [m for m in fallbacks if m and m != primary_model]
    tried: list[str] = []

    def _on_fallback(failed_mid: str):
        tried.append(failed_mid)
        next_model = models_to_try[len(tried):][:1] or None
        logger.info(
            json.dumps(
                {
                    "event": "vertex_model_fallback",
                    "path": log_path,
                    "failedModel": failed_mid,
                    "next": next_model,
                }
            )
        )

    gateway = VertexGateway(
        project=project,
        region=region,
        primary_model=primary_model,
        fallbacks=fallbacks,
        temperature=temperature,
        max_tokens=max_tokens,
        client_cls=client_cls,
    )

    # Prefer async JSON path if supported, else async non-JSON fallback
    try:
        from ..json_schemas import REPLY_SCHEMA

        result = await gateway.agenerate_text_json(
            prompt=prompt,
            response_schema=REPLY_SCHEMA,
            system_instruction=system_instruction,
            log_fallback=_on_fallback,
        )
        def _record_model():
            _last_model_used_var.set(getattr(gateway, "last_model_used", primary_model))

        obj = _extract_json_payload(result)
        reply = _maybe_extract_patient_reply(obj)
        if reply:
            _record_model()
            path = (log_path or "").lower()
            if "legacy" in path:
                return reply
            return json.dumps({"patient_reply": reply}, separators=(",", ":"))
        _record_model()
        try:
            path = (log_path or "").lower()
            if "legacy" in path and ("```" in result or "json" in (result or "").lower()):
                plain = await gateway.agenerate_text(
                    prompt=prompt,
                    system_instruction=system_instruction,
                    log_fallback=_on_fallback,
                )
                return plain
            return result
        except Exception as e:
            _logger.warning("Secondary agenerate_text call failed for legacy path: %s", e)
            return result
    except VertexAIError:
        raise
    except Exception as e:
        _logger.error("Primary avertex call failed: %s", e)
        result = await gateway.agenerate_text(
            prompt=prompt,
            system_instruction=system_instruction,
            log_fallback=_on_fallback,
        )
        _last_model_used_var.set(getattr(gateway, "last_model_used", primary_model))
        return result


async def avertex_call_with_fallback_json(
    *,
    project: str,
    region: str,
    primary_model: str,
    fallbacks: list[str],
    temperature: float,
    max_tokens: int,
    prompt: str,
    system_instruction: str | None,
    schema: dict,
    log_path: str,
    logger,
    client_cls: type = VertexClient,
) -> str:
    """Async variant of vertex_call_with_fallback_json."""
    from ..json_schemas import vertex_response_schema
    from .vertex_gateway import VertexGateway

    models_to_try = [primary_model] + [m for m in fallbacks if m and m != primary_model]
    tried: list[str] = []

    def _on_fallback(failed_mid: str):
        tried.append(failed_mid)
        next_model = models_to_try[len(tried):][:1] or None
        logger.info(
            json.dumps(
                {
                    "event": "vertex_model_fallback",
                    "path": log_path,
                    "failedModel": failed_mid,
                    "next": next_model,
                }
            )
        )

    gateway = VertexGateway(
        project=project,
        region=region,
        primary_model=primary_model,
        fallbacks=fallbacks,
        temperature=temperature,
        max_tokens=max_tokens,
        client_cls=client_cls,
    )

    result = await gateway.agenerate_text_json(
        prompt=prompt,
        response_schema=vertex_response_schema(schema),
        system_instruction=system_instruction,
        log_fallback=_on_fallback,
    )
    _last_model_used_var.set(getattr(gateway, "last_model_used", primary_model))
    obj = _extract_json_payload(result)
    if obj is not None:
        try:
            reply = _maybe_extract_patient_reply(obj)
            if reply:
                return json.dumps({"patient_reply": reply}, separators=(",", ":"))
            return json.dumps(obj, separators=(",", ":"))
        except Exception as e:
            _logger.warning("Failed to re-serialize JSON payload: %s", e)
            pass
    return result
