import json

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
