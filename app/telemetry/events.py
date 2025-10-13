"""
Telemetry utilities for structured JSON logging with size caps.

Phase 1 extraction goal: centralize logging helpers used by app.main
so they are reusable and testable without FastAPI context. Keep
functions small and pure.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional


def truncate_for_log(s: str, cap: int) -> str:
    """Safely truncate a string to a maximum length `cap`.

    If `s` is not a string or len() fails, returns the original value's str().
    """
    try:
        if not isinstance(s, str):
            s = str(s)
        return s if len(s) <= cap else s[:cap]
    except Exception:
        try:
            return str(s)
        except Exception:
            return ""


def log_event(logger, event_name: str, *, caps: Optional[Dict[str, int]] = None, **fields: Any) -> None:
    """Emit a single JSON event line via the provided logger.

    - logger: a standard logging.Logger-like object with .info()
    - event_name: value for the `event` field
    - caps: optional mapping of field names -> max length (applied to str values)
    - **fields: arbitrary event fields
    """
    payload: Dict[str, Any] = {"event": event_name}
    payload.update(fields or {})

    # Apply caps to selected fields
    if caps:
        for key, limit in caps.items():
            if key in payload and payload[key] is not None:
                payload[key] = truncate_for_log(payload[key], int(limit))

    try:
        logger.info(json.dumps(payload))
    except Exception:
        # Fall back to best-effort string logging if JSON serialization fails
        try:
            logger.info(str(payload))
        except Exception:
            pass


__all__ = ["truncate_for_log", "log_event"]
