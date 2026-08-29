"""InMemoryStore must exclude mutation while it is serializing itself.

Every write used to happen on the event-loop thread, which serialized persistence for
free. Session pruning now runs in a worker threadpool after the response, so a prune can
call ``pop`` while the loop thread services another request and calls ``__setitem__``.
Both reach ``_persist``.

Two failure modes without the lock and the per-write temp file:
  * ``json.dump`` walks ``self._store`` while another thread mutates it, raising
    "dictionary changed size during iteration";
  * both writers open the same ``<path>.tmp``, interleave their output, and each renames
    it over the real file, leaving truncated or mixed JSON.

Neither reproduces reliably by simply hammering threads — CPython's serializer usually
finishes inside one GIL slice. So the persist step is slowed deliberately here, which
makes the interleaving deterministic rather than a coin flip.
"""

from __future__ import annotations

import json
import threading
import time

import pytest

from app.memory_store import InMemoryStore


def test_mutation_is_blocked_while_the_store_is_being_serialized(tmp_path, monkeypatch):
    """A writer must not be able to mutate the dict mid-serialization."""
    path = tmp_path / "session_memory.json"
    store = InMemoryStore(persist_path=str(path))
    for i in range(50):
        store[f"seed{i}"] = {"history": []}

    dump_started = threading.Event()
    release_dump = threading.Event()
    real_dump = json.dump
    first_dump = threading.Event()

    def slow_dump(obj, fp, **kwargs):
        # Only the FIRST serialization is held open. If every call blocked, the mutator
        # would stall inside its own _persist and the test would pass whether or not the
        # lock exists — which is exactly how an earlier version of this test fooled itself.
        if not first_dump.is_set():
            first_dump.set()
            dump_started.set()
            release_dump.wait(timeout=5)
        return real_dump(obj, fp, **kwargs)

    monkeypatch.setattr("app.memory_store.json.dump", slow_dump)

    errors: list[BaseException] = []

    def persist_in_background():
        try:
            store["trigger"] = {"history": []}
        except BaseException as e:  # noqa: BLE001 - surfaced through errors
            errors.append(e)

    persister = threading.Thread(target=persist_in_background)
    persister.start()
    assert dump_started.wait(timeout=5), "serialization never started"

    mutated = threading.Event()

    def mutate():
        try:
            # Blocks until the persister releases the lock, if the lock works.
            store["late"] = {"history": []}
            mutated.set()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    mutator = threading.Thread(target=mutate)
    mutator.start()

    # The mutation must NOT have landed while serialization is in flight.
    time.sleep(0.2)
    assert not mutated.is_set(), (
        "a second thread mutated the store while it was being serialized; "
        "_persist is not protected by the lock"
    )

    release_dump.set()
    persister.join(timeout=10)
    mutator.join(timeout=10)

    assert not errors, f"concurrent access raised: {errors[:3]}"
    assert mutated.is_set(), "the blocked mutation never completed"

    with open(path, encoding="utf-8") as f:
        assert isinstance(json.load(f), dict)


def test_persist_leaves_no_temp_files_behind(tmp_path):
    """A shared '<path>.tmp' is what let two writers clobber each other."""
    path = tmp_path / "session_memory.json"
    store = InMemoryStore(persist_path=str(path))
    for i in range(20):
        store[f"k{i}"] = {"history": []}

    leftovers = [p.name for p in tmp_path.iterdir() if p.name != path.name]
    assert not leftovers, f"temp files left behind: {leftovers}"


def test_persisted_file_stays_loadable_under_concurrent_writers(tmp_path):
    """End-to-end sanity: many threads, still one valid JSON document afterwards."""
    path = tmp_path / "session_memory.json"
    store = InMemoryStore(persist_path=str(path))
    for i in range(200):
        store[f"seed{i}"] = {"history": [{"role": "assistant", "content": "y" * 200}]}

    errors: list[BaseException] = []

    def churn(writer: bool) -> None:
        try:
            for i in range(100):
                if writer:
                    store[f"w{i}"] = {"history": [{"role": "user", "content": "x" * 200}]}
                else:
                    store.pop(f"seed{i}", None)
                    store.items()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=churn, args=(i % 2 == 0,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, f"concurrent access raised: {errors[:3]}"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert InMemoryStore(persist_path=str(path)).__len__() == len(data)


@pytest.mark.parametrize("method", ["__setitem__", "pop", "items"])
def test_mutating_methods_take_the_lock(method):
    """Guard against a future edit dropping the lock from one of these."""
    import inspect

    source = inspect.getsource(getattr(InMemoryStore, method))
    assert "self._lock" in source, (
        f"InMemoryStore.{method} no longer acquires self._lock; concurrent prune and "
        "request handling can then corrupt the persisted file."
    )
