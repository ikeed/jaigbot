from __future__ import annotations

import hashlib
import time
from typing import Any


CURRENT_THREAD_KEY_PREFIX = "chainlit:current_thread:"
THREAD_KEY_PREFIX = "chainlit:thread:"


def _store() -> Any:
    from app.main import _MEMORY_STORE

    return _MEMORY_STORE


def _key(user_identifier: str) -> str:
    digest = hashlib.sha256(user_identifier.encode("utf-8")).hexdigest()
    return f"{CURRENT_THREAD_KEY_PREFIX}{digest}"


def get_current_thread_id(user_identifier: str | None) -> str | None:
    if not user_identifier:
        return None
    store = _store()
    value = store.get(_key(user_identifier))
    if isinstance(value, dict):
        thread_id = value.get("thread_id")
    elif isinstance(value, str):
        thread_id = value
    else:
        thread_id = None

    if not thread_id:
        return None

    if store.get(f"{THREAD_KEY_PREFIX}{thread_id}") is None:
        clear_current_thread_id(user_identifier)
        return None
    return thread_id


def set_current_thread_id(user_identifier: str | None, thread_id: str | None) -> None:
    if not user_identifier or not thread_id:
        return
    _store()[_key(user_identifier)] = {
        "thread_id": thread_id,
        "updated": time.time(),
    }


def clear_current_thread_id(user_identifier: str | None) -> None:
    if not user_identifier:
        return
    _store().pop(_key(user_identifier), None)
