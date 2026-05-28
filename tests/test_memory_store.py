import json

import pytest
from chainlit.types import Pagination, ThreadFilter
from chainlit.user import User

from app.chainlit_memory_data_layer import MemoryDataLayer
from app.memory_store import InMemoryStore


def test_in_memory_store_can_reload_from_persisted_file(tmp_path):
    path = tmp_path / "session_memory.json"
    store = InMemoryStore(persist_path=str(path))
    store["sid"] = {
        "history": [{"role": "system", "content": "Person: Sarah"}],
        "full_history": [{"role": "system", "content": "Person: Sarah", "time": 1.0}],
        "character": "Specific Persona: Sarah",
        "scene": "clinic",
        "active_connections": ["dead-websocket"],
    }

    reloaded = InMemoryStore(persist_path=str(path))

    mem = reloaded.get("sid")
    assert mem is not None
    assert mem["history"][0]["content"] == "Person: Sarah"
    assert mem["character"] == "Specific Persona: Sarah"
    assert mem["active_connections"] == []


def test_in_memory_store_pop_updates_persisted_file(tmp_path):
    path = tmp_path / "session_memory.json"
    store = InMemoryStore(persist_path=str(path))
    store["sid"] = {"history": []}

    assert store.pop("sid") == {"history": []}

    with path.open("r", encoding="utf-8") as f:
        assert json.load(f) == {}


@pytest.mark.asyncio
async def test_chainlit_memory_data_layer_persists_threads_and_steps():
    store = InMemoryStore()
    layer = MemoryDataLayer(store)

    user = await layer.create_user(User(identifier="doctor@example.com"))
    await layer.update_thread("thread-1", name="hello", user_id=user.id, metadata={"session_id": "thread-1"})
    await layer.create_step(
        {
            "id": "step-1",
            "threadId": "thread-1",
            "parentId": None,
            "createdAt": "2026-01-01T00:00:00Z",
            "command": None,
            "modes": None,
            "start": "2026-01-01T00:00:00Z",
            "end": "2026-01-01T00:00:00Z",
            "output": "Person: Sarah",
            "name": "System",
            "type": "assistant_message",
            "language": None,
            "showInput": None,
            "isError": False,
            "waitForAnswer": False,
            "metadata": {},
            "tags": None,
        }
    )

    thread = await layer.get_thread("thread-1")

    assert thread["userIdentifier"] == "doctor@example.com"
    assert thread["metadata"]["session_id"] == "thread-1"
    assert thread["steps"][0]["output"] == "Person: Sarah"


@pytest.mark.asyncio
async def test_chainlit_memory_data_layer_lists_user_threads_only():
    store = InMemoryStore()
    layer = MemoryDataLayer(store)

    user_a = await layer.create_user(User(identifier="a@example.com"))
    user_b = await layer.create_user(User(identifier="b@example.com"))
    await layer.update_thread("thread-a", user_id=user_a.id)
    await layer.update_thread("thread-b", user_id=user_b.id)

    result = await layer.list_threads(Pagination(first=10), ThreadFilter(userId=user_a.id))

    assert [thread["id"] for thread in result.data] == ["thread-a"]


@pytest.mark.asyncio
async def test_chainlit_memory_data_layer_hides_alias_threads():
    store = InMemoryStore()
    layer = MemoryDataLayer(store)

    user = await layer.create_user(User(identifier="doctor@example.com"))
    other_user = await layer.create_user(User(identifier="other@example.com"))
    await layer.update_thread("thread-original", user_id=user.id, metadata={"session_id": "thread-original"})
    await layer.update_thread("thread-alias", user_id=user.id, metadata={"session_id": "thread-original"})
    await layer.update_thread("other-original", user_id=other_user.id, metadata={"session_id": "other-original"})
    await layer.update_thread("other-alias", user_id=user.id, metadata={"session_id": "other-original"})

    result = await layer.list_threads(Pagination(first=10), ThreadFilter(userId=user.id))

    assert {thread["id"] for thread in result.data} == {"other-alias", "thread-original"}
