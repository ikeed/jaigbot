import pytest
from fastapi.testclient import TestClient
from app.main import app, _MEMORY_STORE

client = TestClient(app)

def test_init_session_backend_persona():
    # Remove from memory store for a fresh test
    sid = "test-sid-backend-persona"
    _MEMORY_STORE.pop(sid, None)
    
    # We pass personaId but no character/scene
    payload = {
        "sessionId": sid,
        "personaId": "Jasmine"
    }
    
    response = client.post("/session", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "ok"
    assert data["sessionId"] == sid
    assert "character" in data
    assert "scene" in data
    assert "initialCard" in data
    
    # Check if Jasmine is in the character
    assert "Jasmine" in data["character"]
    # Check if Jasmine is in the initial card
    assert "Jasmine" in data["initialCard"]
    
    # Check if memory store is updated
    assert sid in _MEMORY_STORE
    mem = _MEMORY_STORE[sid]
    assert mem["character"] == data["character"]
    assert mem["scene"] == data["scene"]
    assert len(mem["history"]) == 1
    assert mem["history"][0]["content"] == data["initialCard"]

def test_init_session_persists_across_calls():
    sid = "test-sid-persist"
    _MEMORY_STORE.pop(sid, None)
    
    # First call with persona
    client.post("/session", json={"sessionId": sid, "personaId": "Jasmine"})
    
    # Second call (e.g. refresh)
    response = client.post("/session", json={"sessionId": sid})
    data = response.json()
    
    assert data["character"] is not None
    assert "Jasmine" in data["character"]
    assert "Jasmine" in data["initialCard"]
    
    # Verify no duplicate history entries in memory store
    mem = _MEMORY_STORE[sid]
    assert len(mem["history"]) == 1

def test_init_session_does_not_reseed_if_history_exists():
    sid = "test-sid-no-reseed"
    _MEMORY_STORE.pop(sid, None)
    
    # Initialize session
    client.post("/session", json={"sessionId": sid, "personaId": "Jasmine"})
    
    # Add a user message to history
    mem = _MEMORY_STORE[sid]
    mem["history"].append({"role": "user", "content": "Hello"})
    mem["full_history"].append({"role": "user", "content": "Hello"})
    assert len(mem["history"]) == 2
    
    # Re-initialize (e.g. page refresh)
    response = client.post("/session", json={"sessionId": sid})
    assert response.status_code == 200
    
    # Verify history is still length 2 (not reset or re-seeded)
    mem = _MEMORY_STORE[sid]
    assert len(mem["history"]) == 2
    assert mem["history"][1]["content"] == "Hello"
    assert mem["history"][0]["role"] == "assistant" # Scenario card

def test_init_session_already_active():
    sid = "test-sid-active"
    conn1 = "conn-1"
    conn2 = "conn-2"
    _MEMORY_STORE.pop(sid, None)
    
    # First connection
    resp1 = client.post("/session", json={"sessionId": sid, "connectionId": conn1})
    assert resp1.status_code == 200
    assert resp1.json()["alreadyActive"] is False
    
    # Second connection with DIFFERENT connectionId
    resp2 = client.post("/session", json={"sessionId": sid, "connectionId": conn2})
    assert resp2.status_code == 200
    assert resp2.json()["alreadyActive"] is True
    
    # Re-connect first connection
    resp3 = client.post("/session", json={"sessionId": sid, "connectionId": conn1})
    assert resp3.status_code == 200
    assert resp3.json()["alreadyActive"] is False
