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


def test_in_memory_store_recovers_from_corrupt_persisted_file(tmp_path):
    path = tmp_path / "session_memory.json"
    path.write_text("{", encoding="utf-8")

    store = InMemoryStore(persist_path=str(path))

    assert store.items() == []


def test_in_memory_store_ignores_persist_failure(tmp_path):
    path = tmp_path / "session_memory.json"
    store = InMemoryStore(persist_path=str(path))
    path.mkdir()

    store["sid"] = {"history": []}

    assert store["sid"] == {"history": []}


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
    assert "chainlit:local:user:doctor@example.com" in dict(store.items())
    assert "chainlit:local:thread:thread-1" in dict(store.items())


@pytest.mark.asyncio
async def test_chainlit_memory_data_layer_discards_transient_disconnect_errors():
    store = InMemoryStore()
    store["chainlit:local:thread:thread-1"] = {
        "id": "thread-1",
        "steps": [
            {
                "id": "restart-error",
                "threadId": "thread-1",
                "type": "assistant_message",
                "name": "Error",
                "isError": True,
                "output": "All connection attempts failed",
            },
            {
                "id": "real-message",
                "threadId": "thread-1",
                "type": "assistant_message",
                "name": "Assistant",
                "isError": False,
                "output": "Hello",
            },
        ],
    }
    layer = MemoryDataLayer(store)

    thread = await layer.get_thread("thread-1")
    await layer.create_step(
        {
            "id": "another-restart-error",
            "threadId": "thread-1",
            "type": "assistant_message",
            "name": "Error",
            "isError": True,
            "output": "All connection attempts failed",
        }
    )

    assert [step["id"] for step in thread["steps"]] == ["real-message"]
    assert [step["id"] for step in store["chainlit:local:thread:thread-1"]["steps"]] == [
        "real-message"
    ]


@pytest.mark.asyncio
async def test_chainlit_memory_data_layer_reads_legacy_thread_keys():
    store = InMemoryStore()
    store["chainlit:thread:legacy-thread"] = {
        "id": "legacy-thread",
        "createdAt": "2026-01-01T00:00:00Z",
        "name": "legacy",
        "userId": None,
        "userIdentifier": "doctor@example.com",
        "tags": None,
        "metadata": {"session_id": "legacy-thread"},
        "steps": [],
        "elements": [],
    }
    layer = MemoryDataLayer(store)

    thread = await layer.get_thread("legacy-thread")

    assert thread["id"] == "legacy-thread"


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
