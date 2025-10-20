import json
import re
from typing import Callable, Optional

from ..vertex import VertexClient

# Track last model used by the most recent gateway call for tests/telemetry
_LAST_MODEL_USED: Optional[str] = None


def get_last_model_used() -> Optional[str]:
    return _LAST_MODEL_USED


def _extract_json_payload(text: str) -> Optional[object]:
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
            return json.loads(body)
        except Exception:
            pass
    # Second pass: unlabeled fences
    for _, body in matches:
        try:
            return json.loads(body)
        except Exception:
            pass

    # 2) Minimal cleanup fallback: remove raw fence markers/backticks and try once
    cleaned = s.replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return None


def _maybe_extract_patient_reply(obj: Optional[dict]) -> Optional[str]:
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
    system_instruction: Optional[str],
    log_path: str,
    logger,
    client_cls: type = VertexClient,
) -> str:
    """Generate a text response using Vertex with model fallback logging.

    Preserves the same event shape used by existing logs. Tries JSON schema path first
    (reply schema embedded via gateway) and falls back to plain text generation when
    unsupported.
    """
    global _LAST_MODEL_USED
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

    # Prefer JSON path if supported, else non-JSON fallback
    try:
        from ..json_schemas import REPLY_SCHEMA

        result = gateway.generate_text_json(
            prompt=prompt,
            response_schema=REPLY_SCHEMA,
            system_instruction=system_instruction,
            log_fallback=_on_fallback,
        )
        # If the model wrapped the JSON in prose/fences, extract the JSON and return patient_reply
        obj = _extract_json_payload(result)
        reply = _maybe_extract_patient_reply(obj)
        if reply:
            _LAST_MODEL_USED = getattr(gateway, "last_model_used", primary_model)
            # Maintain existing contract for text path: return a JSON string envelope
            return json.dumps({"patient_reply": reply}, separators=(",", ":"))
        # Record last model used and return raw result (legacy behavior)
        _LAST_MODEL_USED = getattr(gateway, "last_model_used", primary_model)
        return result
    except Exception:
        result = gateway.generate_text(
            prompt=prompt,
            system_instruction=system_instruction,
            log_fallback=_on_fallback,
        )
        _LAST_MODEL_USED = getattr(gateway, "last_model_used", primary_model)
        return result


def vertex_call_with_fallback_json(
    *,
    project: str,
    region: str,
    primary_model: str,
    fallbacks: list[str],
    temperature: float,
    max_tokens: int,
    prompt: str,
    system_instruction: Optional[str],
    schema: dict,
    log_path: str,
    logger,
    client_cls: type = VertexClient,
) -> str:
    """Generate a JSON-constrained response using Vertex with model fallback logging."""
    global _LAST_MODEL_USED
    from .vertex_gateway import VertexGateway
    from ..json_schemas import vertex_response_schema

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

    result = gateway.generate_text_json(
        prompt=prompt,
        response_schema=vertex_response_schema(schema),
        system_instruction=system_instruction,
        log_fallback=_on_fallback,
    )
    _LAST_MODEL_USED = getattr(gateway, "last_model_used", primary_model)
    # If JSON is wrapped, extract and re-serialize compactly for consumers that expect raw JSON
    obj = _extract_json_payload(result)
    if obj is not None:
        try:
            # If it's our REPLY-like schema, prefer returning the patient_reply scalar for compatibility
            reply = _maybe_extract_patient_reply(obj)  # type: ignore[arg-type]
            if reply:
                return json.dumps({"patient_reply": reply}, separators=(",", ":"))
            return json.dumps(obj, separators=(",", ":"))
        except Exception:
            pass
    return result
