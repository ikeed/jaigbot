from __future__ import annotations

import hashlib
import uuid
from typing import Any, Dict, List, Optional, cast

from chainlit.data.base import BaseDataLayer
from chainlit.element import ElementDict
from chainlit.step import StepDict
from chainlit.types import Feedback, PageInfo, PaginatedResponse, Pagination, ThreadDict, ThreadFilter
from chainlit.user import PersistedUser, User
from chainlit.utils import utc_now

from app.config import settings

LEGACY_USER_KEY_PREFIX = "chainlit:user:"
LEGACY_THREAD_KEY_PREFIX = "chainlit:thread:"
TRANSIENT_DISCONNECT_ERROR_OUTPUTS = {"All connection attempts failed"}


def _user_key_prefix() -> str:
    return f"chainlit:{settings.APP_ENV}:user:"


def _thread_key_prefix() -> str:
    return f"chainlit:{settings.APP_ENV}:thread:"


def _user_id(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()


def _user_key(identifier: str) -> str:
    return f"{_user_key_prefix()}{identifier}"


def _legacy_user_key(identifier: str) -> str:
    return f"{LEGACY_USER_KEY_PREFIX}{identifier}"


def _thread_key(thread_id: str) -> str:
    return f"{_thread_key_prefix()}{thread_id}"


def _legacy_thread_key(thread_id: str) -> str:
    return f"{LEGACY_THREAD_KEY_PREFIX}{thread_id}"


def _thread_keys(thread_id: str) -> List[str]:
    return [_thread_key(thread_id), _legacy_thread_key(thread_id)]


def _is_user_key(key: str) -> bool:
    return key.startswith(_user_key_prefix()) or key.startswith(LEGACY_USER_KEY_PREFIX)


def _is_thread_key(key: str) -> bool:
    return key.startswith(_thread_key_prefix()) or key.startswith(LEGACY_THREAD_KEY_PREFIX)


def _step_time(step: Dict[str, Any]) -> str:
    return step.get("start") or step.get("createdAt") or step.get("end") or ""


def _ordered_steps(steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return steps in the order Chainlit's resume renderer expects.

    Chainlit can persist run steps after the messages created inside those runs.
    On resume, child messages need their parent run available first or the UI can
    hide them. Sorting by step start/created time restores that relationship.
    """
    return sorted(steps or [], key=lambda step: (_step_time(step), step.get("id") or ""))


def _is_transient_disconnect_error_step(step: Dict[str, Any]) -> bool:
    return (
        step.get("type") == "assistant_message"
        and step.get("name") == "Error"
        and step.get("isError") is True
        and str(step.get("output") or "").strip() in TRANSIENT_DISCONNECT_ERROR_OUTPUTS
    )


def _canonical_session_id(thread: Dict[str, Any]) -> str:
    metadata = thread.get("metadata") or {}
    return str(metadata.get("session_id") or thread.get("id") or "")


class MemoryDataLayer(BaseDataLayer):
    """Chainlit data layer backed by the app memory store.

    The app already supports process-local memory, file-backed local memory, and
    Redis/Memorystore through one small dict-like abstraction. Reusing that store
    lets Chainlit persist threads across Cloud Run instance churn without adding
    another database just for UI transcript restoration.
    """

    def __init__(self, store: Any) -> None:
        self.store = store

    def _get(self, key: str) -> Dict[str, Any] | None:
        value = self.store.get(key)
        return dict(value) if isinstance(value, dict) else None

    def _put(self, key: str, value: Dict[str, Any]) -> None:
        self.store[key] = value

    def _get_first(self, keys: List[str]) -> Dict[str, Any] | None:
        for key in keys:
            value = self._get(key)
            if value:
                return value
        return None

    def _get_thread(self, thread_id: str) -> Dict[str, Any] | None:
        return self._get_first(_thread_keys(thread_id))

    def _clean_thread_steps(self, thread: Dict[str, Any]) -> Dict[str, Any]:
        original_steps = thread.get("steps", [])
        clean_steps = _ordered_steps([
            step for step in original_steps
            if not _is_transient_disconnect_error_step(step)
        ])
        if clean_steps != original_steps:
            thread["steps"] = clean_steps
            self._put(_thread_key(thread["id"]), thread)
        else:
            thread["steps"] = clean_steps
        return thread

    def _ensure_thread(self, thread_id: str) -> Dict[str, Any]:
        key = _thread_key(thread_id)
        thread = self._get_thread(thread_id)
        if thread:
            thread.setdefault("steps", [])
            thread.setdefault("elements", [])
            thread.setdefault("metadata", {})
            return self._clean_thread_steps(thread)

        thread = {
            "id": thread_id,
            "createdAt": utc_now(),
            "name": None,
            "userId": None,
            "userIdentifier": None,
            "tags": None,
            "metadata": {},
            "steps": [],
            "elements": [],
        }
        self._put(key, thread)
        return thread

    def _find_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        for key, value in self.store.items():
            if _is_user_key(key) and value.get("id") == user_id:
                return value
        return None

    async def get_user(self, identifier: str) -> Optional[PersistedUser]:
        user = self._get_first([_user_key(identifier), _legacy_user_key(identifier)])
        if not user:
            return None
        return PersistedUser(
            id=user["id"],
            createdAt=user["createdAt"],
            identifier=user["identifier"],
            display_name=user.get("display_name"),
            metadata=user.get("metadata") or {},
        )

    async def create_user(self, user: User) -> Optional[PersistedUser]:
        existing = await self.get_user(user.identifier)
        if existing:
            return existing

        persisted = {
            "id": _user_id(user.identifier),
            "createdAt": utc_now(),
            "identifier": user.identifier,
            "display_name": user.display_name,
            "metadata": user.metadata or {},
        }
        self._put(_user_key(user.identifier), persisted)
        return PersistedUser(**persisted)

    async def delete_feedback(self, feedback_id: str) -> bool:
        return True

    async def upsert_feedback(self, feedback: Feedback) -> str:
        return feedback.id or str(uuid.uuid4())

    async def create_element(self, element: Any):
        thread = self._ensure_thread(element.thread_id)
        elements = [e for e in thread.get("elements", []) if e.get("id") != element.id]
        elements.append(element.to_dict())
        thread["elements"] = elements
        self._put(_thread_key(thread["id"]), thread)

    async def get_element(self, thread_id: str, element_id: str) -> Optional[ElementDict]:
        thread = self._get_thread(thread_id)
        if not thread:
            return None
        for element in thread.get("elements", []) or []:
            if element.get("id") == element_id:
                return cast(ElementDict, element)
        return None

    async def delete_element(self, element_id: str, thread_id: Optional[str] = None):
        if not thread_id:
            return
        thread = self._get_thread(thread_id)
        if not thread:
            return
        thread["elements"] = [e for e in thread.get("elements", []) if e.get("id") != element_id]
        self._put(_thread_key(thread_id), thread)

    async def create_step(self, step_dict: Dict[str, Any]):
        if _is_transient_disconnect_error_step(step_dict):
            return
        thread_id = step_dict["threadId"]
        thread = self._ensure_thread(thread_id)
        steps = [s for s in thread.get("steps", []) if s.get("id") != step_dict.get("id")]
        steps.append(step_dict)
        thread["steps"] = _ordered_steps(steps)
        self._put(_thread_key(thread_id), thread)

    async def update_step(self, step_dict: Dict[str, Any]):
        await self.create_step(step_dict)

    async def delete_step(self, step_id: str):
        for key, thread in self.store.items():
            if not _is_thread_key(key):
                continue
            thread["steps"] = [s for s in thread.get("steps", []) if s.get("id") != step_id]
            self._put(key, thread)

    async def get_thread_author(self, thread_id: str) -> str:
        thread = self._get_thread(thread_id) or {}
        return thread.get("userIdentifier") or ""

    async def delete_thread(self, thread_id: str):
        for key in _thread_keys(thread_id):
            self.store.pop(key, None)

    async def list_threads(
        self, pagination: Pagination, filters: ThreadFilter
    ) -> PaginatedResponse[ThreadDict]:
        threads: List[ThreadDict] = []
        canonical_thread_ids = {
            value.get("id")
            for key, value in self.store.items()
            if _is_thread_key(key)
            and value.get("id") == _canonical_session_id(value)
            and (not filters.userId or value.get("userId") == filters.userId)
        }
        seen_thread_ids = set()
        for key, value in self.store.items():
            if not _is_thread_key(key):
                continue
            if filters.userId and value.get("userId") != filters.userId:
                continue
            thread_id = value.get("id")
            if thread_id in seen_thread_ids:
                continue
            seen_thread_ids.add(thread_id)
            session_id = _canonical_session_id(value)
            if session_id != thread_id and session_id in canonical_thread_ids:
                continue
            value = dict(value)
            threads.append(cast(ThreadDict, cast(object, self._clean_thread_steps(value))))

        threads.sort(key=lambda t: t.get("createdAt") or "", reverse=True)
        first = pagination.first or len(threads)
        page = threads[:first]
        return PaginatedResponse(
            pageInfo=PageInfo(
                hasNextPage=len(threads) > len(page),
                startCursor=page[0]["id"] if page else None,
                endCursor=page[-1]["id"] if page else None,
            ),
            data=page,
        )

    async def get_thread(self, thread_id: str) -> Optional[ThreadDict]:
        thread = self._get_thread(thread_id)
        if not thread:
            return None
        thread.setdefault("steps", [])
        thread.setdefault("elements", [])
        thread.setdefault("metadata", {})
        return cast(ThreadDict, cast(object, self._clean_thread_steps(thread)))

    async def update_thread(
        self,
        thread_id: str,
        name: Optional[str] = None,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        tags: Optional[List[str]] = None,
    ):
        thread = self._ensure_thread(thread_id)
        if name is not None:
            thread["name"] = name
        if user_id is not None:
            thread["userId"] = user_id
            if user := self._find_user_by_id(user_id):
                thread["userIdentifier"] = user.get("identifier")
        if metadata is not None:
            thread["metadata"] = metadata
        if tags is not None:
            thread["tags"] = tags
        self._put(_thread_key(thread_id), thread)

    async def build_debug_url(self) -> str:
        return ""

    async def close(self) -> None:
        return None

    async def get_favorite_steps(self, user_id: str) -> List[StepDict]:
        favorites: List[StepDict] = []
        for key, value in self.store.items():
            if not _is_thread_key(key) or value.get("userId") != user_id:
                continue
            for step in value.get("steps", []) or []:
                if (step.get("metadata") or {}).get("favorite"):
                    favorites.append(cast(StepDict, step))
        return favorites
