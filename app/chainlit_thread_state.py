from __future__ import annotations

import hashlib
import time
from typing import Any

from app.config import settings
from app.constants import (
    KEY_THREAD_ID,
    KEY_UPDATED,
    PREFIX_CHAINLIT,
    PREFIX_CURRENT_THREAD,
    PREFIX_THREAD,
)

LEGACY_CURRENT_THREAD_KEY_PREFIX = f"{PREFIX_CHAINLIT}:{PREFIX_CURRENT_THREAD}:"
LEGACY_THREAD_KEY_PREFIX = f"{PREFIX_CHAINLIT}:{PREFIX_THREAD}:"


def _current_thread_key_prefix() -> str:
    return f"{PREFIX_CHAINLIT}:{settings.APP_ENV}:{PREFIX_CURRENT_THREAD}:"


def _thread_key_prefix() -> str:
    return f"{PREFIX_CHAINLIT}:{settings.APP_ENV}:{PREFIX_THREAD}:"


def _store() -> Any:
    from app.main import MEMORY_STORE

    return MEMORY_STORE


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


def _thread_record(store: Any, thread_id: str) -> dict[str, Any] | None:
    for key in (f"{_thread_key_prefix()}{thread_id}", f"{LEGACY_THREAD_KEY_PREFIX}{thread_id}"):
        value = store.get(key)
        if isinstance(value, dict):
            return value
    return None


def _thread_belongs_to_user(thread: dict[str, Any] | None, user_identifier: str) -> bool:
    if not isinstance(thread, dict):
        return False
    owner = thread.get("userIdentifier")
    if not isinstance(owner, str) or not owner.strip():
        return False
    return owner.strip().lower() == user_identifier.strip().lower()


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

    thread = _thread_record(store, thread_id)
    if not _thread_exists(store, thread_id) or not _thread_belongs_to_user(thread, user_identifier):
        clear_current_thread_id(user_identifier)
        return None
    return thread_id


def get_current_thread_record(user_identifier: str | None) -> dict[str, Any] | None:
    """Return the persisted current thread's full record for this user, or None.

    Same validation as get_current_thread_id (thread must exist and belong to
    the user); returns the stored thread dict so callers can resume it without
    a second lookup.
    """
    thread_id = get_current_thread_id(user_identifier)
    if not thread_id:
        return None
    return _thread_record(_store(), thread_id)


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
