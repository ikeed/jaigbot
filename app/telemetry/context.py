from __future__ import annotations

import contextvars
from typing import Any


_log_context_var: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "log_context", default={}
)


def get_log_context() -> dict[str, Any]:
    return dict(_log_context_var.get() or {})


def set_log_context(**fields: Any) -> contextvars.Token:
    context = get_log_context()
    for key, value in fields.items():
        if value is not None:
            context[key] = value
    return _log_context_var.set(context)


def clear_log_context(token: contextvars.Token) -> None:
    _log_context_var.reset(token)

