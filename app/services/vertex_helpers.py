import json
from typing import Callable, Optional

from ..vertex import VertexClient

# Track last model used by the most recent gateway call for tests/telemetry
_LAST_MODEL_USED: Optional[str] = None

def get_last_model_used() -> Optional[str]:
    return _LAST_MODEL_USED


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
        # Record last model used
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
    return result
