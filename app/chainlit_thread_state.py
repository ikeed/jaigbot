from __future__ import annotations

import hashlib
import time
from typing import Any

from app.config import settings
from app.constants import (
    PREFIX_CHAINLIT,
    PREFIX_CURRENT_THREAD,
    PREFIX_THREAD,
    KEY_THREAD_ID,
    KEY_UPDATED
)

LEGACY_CURRENT_THREAD_KEY_PREFIX = f"{PREFIX_CHAINLIT}:{PREFIX_CURRENT_THREAD}:"
LEGACY_THREAD_KEY_PREFIX = f"{PREFIX_CHAINLIT}:{PREFIX_THREAD}:"


def _current_thread_key_prefix() -> str:
    return f"{PREFIX_CHAINLIT}:{settings.APP_ENV}:{PREFIX_CURRENT_THREAD}:"


def _thread_key_prefix() -> str:
    return f"{PREFIX_CHAINLIT}:{settings.APP_ENV}:{PREFIX_THREAD}:"


def _store() -> Any:
    from app.main import _MEMORY_STORE

    return _MEMORY_STORE


def _key(user_identifier: str) -> str:
    digest = hashlib.sha256(user_identifier.encode("utf-8")).hexdigest()
    return f"{_current_thread_key_prefix()}{digest}"


def _legacy_key(user_identifier: str) -> str:
    digest = hashlib.sha256(user_identifier.encode("utf-8")).hexdigest()
    return f"{LEGACY_CURRENT_THREAD_KEY_PREFIX}{digest}"


def _thread_exists(store: Any, thread_id: str) -> bool:
    return (
        store.get(f"{_thread_key_prefix()}{thread_id}") is not None
        or store.get(f"{LEGACY_THREAD_KEY_PREFIX}{thread_id}") is not None
    )


def get_current_thread_id(user_identifier: str | None) -> str | None:
    if not user_identifier:
        return None
    store = _store()
    value = store.get(_key(user_identifier)) or store.get(_legacy_key(user_identifier))
    if isinstance(value, dict):
        thread_id = value.get(KEY_THREAD_ID)
    elif isinstance(value, str):
        thread_id = value
    else:
        thread_id = None

    if not thread_id:
        return None

    if not _thread_exists(store, thread_id):
        clear_current_thread_id(user_identifier)
        return None
    return thread_id


def set_current_thread_id(user_identifier: str | None, thread_id: str | None) -> None:
    if not user_identifier or not thread_id:
        return
    _store()[_key(user_identifier)] = {
        KEY_THREAD_ID: thread_id,
        KEY_UPDATED: time.time(),
    }


def clear_current_thread_id(user_identifier: str | None) -> None:
    if not user_identifier:
        return
    _store().pop(_key(user_identifier), None)
    _store().pop(_legacy_key(user_identifier), None)
