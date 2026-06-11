from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.constants import KEY_AIMS_STATE, KEY_COACH_POST, KEY_AIMS_METRICS


def normalize_module_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip().lower()
    return candidate or None


def resolve_archive_module_id(data: Mapping[str, Any]) -> str | None:
    """Resolve a persisted archive/session payload to a module id.

    Legacy inference is intentionally narrow and AIMS-specific. Unknown legacy
    payload families must return ``None`` so callers can make an explicit
    fallback choice instead of silently guessing a module family.
    """
    explicit_id = (
        normalize_module_id(data.get("module_id"))
        or normalize_module_id((data.get("metadata") or {}).get("moduleId") if isinstance(data.get("metadata"), Mapping) else None)
        or normalize_module_id((data.get("module") or {}).get("id") if isinstance(data.get("module"), Mapping) else None)
    )
    if explicit_id:
        return explicit_id

    if _looks_like_legacy_aims_archive(data):
        return "aims"

    return None


def resolve_thread_metadata_module_id(metadata: Mapping[str, Any]) -> str | None:
    """Resolve persisted Chainlit thread metadata to a module id.

    Legacy inference is intentionally narrow and AIMS-specific. Unknown legacy
    thread families must return ``None`` so resume behavior stays explicit.
    """
    explicit_id = (
        normalize_module_id(metadata.get("module_id"))
        or normalize_module_id((metadata.get("module") or {}).get("id") if isinstance(metadata.get("module"), Mapping) else None)
    )
    if explicit_id:
        return explicit_id

    if _looks_like_legacy_aims_thread(metadata):
        return "aims"

    return None


def _looks_like_legacy_aims_archive(data: Mapping[str, Any]) -> bool:
    analytics = data.get("analytics")
    if isinstance(analytics, Mapping) and KEY_AIMS_METRICS in analytics:
        return True

    module_payload = (data.get("module") or {}).get("payload") if isinstance(data.get("module"), Mapping) else None
    if isinstance(module_payload, Mapping) and module_payload.get("summary") is not None and module_payload.get("analytics") is not None:
        return True

    if data.get(KEY_AIMS_METRICS) is not None or data.get(KEY_AIMS_STATE) is not None or data.get(KEY_COACH_POST) is not None:
        return True

    return False


def _looks_like_legacy_aims_thread(metadata: Mapping[str, Any]) -> bool:
    if metadata.get("personaName") or metadata.get("initialCard"):
        return True

    return bool(
        isinstance(metadata.get("history"), list)
        and metadata.get("character")
        and metadata.get("scene")
    )
