import json
import logging
import sys
import types
from types import SimpleNamespace

import pytest
from chainlit.types import Pagination, ThreadFilter
from chainlit.user import User

from app.chainlit_memory_data_layer import MemoryDataLayer
from app.memory_store import InMemoryStore, RedisStore


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


def test_redis_store_supports_primary_and_fallback_keys(monkeypatch):
    class FakePipeline:
        def __init__(self, client):
            self.client = client
            self.ops = []

        def set(self, key, value):
            self.ops.append(("set", key, value))
            self.client.data[key] = value
            return self

        def expire(self, key, ttl):
            self.ops.append(("expire", key, ttl))
            self.client.expirations[key] = ttl
            return self

        @staticmethod
        def execute():
            return None

    class FakeRedisClient:
        def __init__(self):
            self.data = {
                "aims:session:primary": json.dumps({"value": 1}),
                "legacy:primary": json.dumps({"value": 2}),
                "aims:session:bad": "{",
            }
            self.expirations = {}

        @staticmethod
        def ping():
            return True

        def get(self, key):
            return self.data.get(key)

        def pipeline(self):
            return FakePipeline(self)

        def scan(self, cursor=0, match=None, count=200):
            keys = [k for k in self.data if match is None or k.startswith(match[:-1])]
            return 0, keys

        def mget(self, keys):
            return [self.data.get(key) for key in keys]

        def delete(self, *keys):
            for key in keys:
                self.data.pop(key, None)

    fake_client = FakeRedisClient()
    fake_module = types.SimpleNamespace(
        from_url=lambda url, decode_responses=True: fake_client,
        Redis=lambda **kwargs: fake_client,
    )
    monkeypatch.setitem(sys.modules, "redis", fake_module)

    store = RedisStore(
        url="redis://example.invalid/0",
        prefix="aims:session:",
        fallback_prefixes=["legacy:"],
        ttl=120,
        logger=logging.getLogger("test"),
    )

    assert store.get("primary") == {"value": 1}

    store.set("new", {"hello": "world"})
    assert fake_client.data["aims:session:new"] == json.dumps({"hello": "world"})
    assert fake_client.expirations["aims:session:new"] == 120

    items = dict(store.items())
    assert items["primary"] == {"value": 1}
    assert "bad" not in items
    assert len(store) == 3

    assert store.pop("primary") == {"value": 1}
    assert "aims:session:primary" not in fake_client.data
    assert "legacy:primary" not in fake_client.data


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


@pytest.mark.asyncio
async def test_chainlit_memory_data_layer_reads_legacy_user_and_reuses_existing_user():
    store = InMemoryStore()
    layer = MemoryDataLayer(store)
    store["chainlit:user:doctor@example.com"] = {
        "id": "legacy-user-id",
        "createdAt": "2026-01-01T00:00:00Z",
        "identifier": "doctor@example.com",
        "display_name": "Dr Example",
        "metadata": {"provider": "google"},
    }

    user = await layer.get_user("doctor@example.com")
    created = await layer.create_user(User(identifier="doctor@example.com"))

    assert user.id == "legacy-user-id"
    assert user.display_name == "Dr Example"
    assert created.id == "legacy-user-id"


@pytest.mark.asyncio
async def test_chainlit_memory_data_layer_feedback_stubs_are_chainlit_compatible():
    layer = MemoryDataLayer(InMemoryStore())

    generated_id = await layer.upsert_feedback(SimpleNamespace(id=None))
    existing_id = await layer.upsert_feedback(SimpleNamespace(id="feedback-id"))

    assert generated_id
    assert existing_id == "feedback-id"
    assert await layer.delete_feedback("feedback-id") is True


@pytest.mark.asyncio
async def test_chainlit_memory_data_layer_element_crud_and_noops():
    store = InMemoryStore()
    layer = MemoryDataLayer(store)
    element = SimpleNamespace(
        id="element-1",
        thread_id="thread-1",
        to_dict=lambda: {"id": "element-1", "name": "file.txt"},
    )

    await layer.delete_element("element-1")
    await layer.delete_element("element-1", thread_id="missing-thread")
    assert await layer.get_element("missing-thread", "element-1") is None

    await layer.create_element(element)
    assert await layer.get_element("thread-1", "element-1") == {
        "id": "element-1",
        "name": "file.txt",
    }

    replacement = SimpleNamespace(
        id="element-1",
        thread_id="thread-1",
        to_dict=lambda: {"id": "element-1", "name": "updated.txt"},
    )
    await layer.create_element(replacement)
    updated_element = await layer.get_element("thread-1", "element-1")
    assert updated_element["name"] == "updated.txt"

    await layer.delete_element("element-1", thread_id="thread-1")
    assert await layer.get_element("thread-1", "element-1") is None


@pytest.mark.asyncio
async def test_chainlit_memory_data_layer_step_delete_update_author_and_thread_delete():
    store = InMemoryStore()
    layer = MemoryDataLayer(store)
    await layer.update_thread("thread-1", metadata={"session_id": "thread-1"})
    await layer.update_thread("thread-1", tags=["tag"])
    await layer.update_step(
        {
            "id": "step-1",
            "threadId": "thread-1",
            "createdAt": "2026-01-01T00:00:02Z",
            "output": "second",
        }
    )
    await layer.create_step(
        {
            "id": "step-0",
            "threadId": "thread-1",
            "createdAt": "2026-01-01T00:00:01Z",
            "output": "first",
        }
    )
    store["chainlit:thread:legacy-thread"] = {
        "id": "legacy-thread",
        "userIdentifier": "legacy@example.com",
        "metadata": {},
        "steps": [{"id": "legacy-step"}],
        "elements": [],
    }

    thread = await layer.get_thread("thread-1")
    assert [step["id"] for step in thread["steps"]] == ["step-0", "step-1"]
    assert thread["tags"] == ["tag"]
    assert await layer.get_thread_author("legacy-thread") == "legacy@example.com"
    assert await layer.get_thread_author("missing-thread") == ""

    await layer.delete_step("step-1")
    await layer.delete_step("legacy-step")
    assert [step["id"] for step in (await layer.get_thread("thread-1"))["steps"]] == ["step-0"]
    assert store["chainlit:thread:legacy-thread"]["steps"] == []

    await layer.delete_thread("thread-1")
    assert await layer.get_thread("thread-1") is None
    assert await layer.build_debug_url() == ""
    assert await layer.close() is None


@pytest.mark.asyncio
async def test_chainlit_memory_data_layer_list_threads_paginates_and_favorites():
    store = InMemoryStore()
    layer = MemoryDataLayer(store)
    user = await layer.create_user(User(identifier="doctor@example.com"))
    await layer.update_thread("older", user_id=user.id, metadata={"session_id": "older"})
    await layer.update_thread("newer", user_id=user.id, metadata={"session_id": "newer"})
    store["chainlit:local:thread:older"]["createdAt"] = "2026-01-01T00:00:00Z"
    store["chainlit:local:thread:newer"]["createdAt"] = "2026-01-02T00:00:00Z"
    store["chainlit:local:thread:newer"]["steps"] = [
        {"id": "favorite", "metadata": {"favorite": True}},
        {"id": "plain", "metadata": {}},
    ]

    page = await layer.list_threads(Pagination(first=1), ThreadFilter(userId=user.id))
    favorites = await layer.get_favorite_steps(user.id)

    assert [thread["id"] for thread in page.data] == ["newer"]
    assert page.pageInfo.hasNextPage is True
    assert page.pageInfo.startCursor == "newer"
    assert page.pageInfo.endCursor == "newer"
    assert [step["id"] for step in favorites] == ["favorite"]
