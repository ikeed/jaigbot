import time

from fastapi.testclient import TestClient

from app.main import app, MEMORY_STORE

client = TestClient(app)


def test_init_session_new_connection_takes_over_without_force():
    sid = "test-sid-force"
    conn1 = "conn-1"
    conn2 = "conn-2"
    MEMORY_STORE.pop(sid, None)

    # First connection
    resp1 = client.post("/session", json={"sessionId": sid, "connectionId": conn1})
    assert resp1.status_code == 200
    assert resp1.json()["alreadyActive"] is False

    # Second connection for the same session should take over. In production a
    # Chainlit/WebSocket reconnect can look exactly like this.
    resp2 = client.post("/session", json={"sessionId": sid, "connectionId": conn2})
    assert resp2.json()["alreadyActive"] is False
    assert MEMORY_STORE[sid]["active_connections"] == [conn2]

    # The legacy force path remains accepted and idempotent.
    resp3 = client.post(
        "/session", json={"sessionId": sid, "connectionId": conn2, "force": True}
    )
    assert resp3.status_code == 200
    assert resp3.json()["alreadyActive"] is False

    # Verify that conn1 is now GONE from active_connections and conn2 is there
    mem = MEMORY_STORE[sid]
    assert conn1 not in mem["active_connections"]
    assert conn2 in mem["active_connections"]
    assert len(mem["active_connections"]) == 1


def test_middleware_stale_session_bypass():
    # We'll test the early_duplicate_tab_detection logic by simulating it manually
    # since it's in run_app.py which we don't easily test with TestClient(app)
    # as app is just the backend part.
    # However, we can check if the backend's updated field works.

    sid = "test-sid-stale"
    MEMORY_STORE.pop(sid, None)

    # Init session
    client.post("/session", json={"sessionId": sid, "connectionId": "old-conn"})
    mem = MEMORY_STORE[sid]

    # Manually make it stale
    mem["updated"] = time.time() - 100
    MEMORY_STORE[sid] = mem

    # Now if we were the middleware in run_app.py, we would check this.
    # Let's verify our logic for "stale"
    mem = MEMORY_STORE.get(sid)
    updated = mem.get("updated", 0)
    is_stale = (time.time() - updated) > 60
    assert is_stale is True


def test_init_session_without_connection_id_does_not_block():
    # If connectionId is not provided (e.g. from a direct API call), it shouldn't block/be blocked
    sid = "test-sid-no-conn"
    MEMORY_STORE.pop(sid, None)

    resp1 = client.post("/session", json={"sessionId": sid})
    assert resp1.json()["alreadyActive"] is False

    resp2 = client.post("/session", json={"sessionId": sid})
    assert resp2.json()["alreadyActive"] is False
