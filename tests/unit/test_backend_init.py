from fastapi.testclient import TestClient

from app.chat_roles import ROLE_SYSTEM
import app.main as m
from app.main import app, MEMORY_STORE
from app.modules.interview.module import create_interview_training_module
from app.services.persona_service import persona_counted_key, persona_counts_key

client = TestClient(app)

def test_init_session_backend_persona():
    # Remove from memory store for a fresh test
    sid = "test-sid-backend-persona"
    MEMORY_STORE.pop(sid, None)
    
    # We pass personaId but no character/scene
    payload = {
        "sessionId": sid,
        "personaId": "Jasmine"
    }
    
    response = client.post("/session", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "ok"
    assert data["moduleId"] == "aims"
    assert data["sessionId"] == sid
    assert "character" in data
    assert "scene" in data
    assert "initialCard" in data
    
    # Check if Jasmine is in the character
    assert "Jasmine" in data["character"]
    # Check if Jasmine is in the initial card
    assert "Jasmine" in data["initialCard"]
    
    # Check if memory store is updated
    assert sid in MEMORY_STORE
    mem = MEMORY_STORE[sid]
    assert mem["character"] == data["character"]
    assert mem["scene"] == data["scene"]
    assert mem["module_id"] == "aims"
    assert len(mem["history"]) == 1
    assert mem["history"][0]["role"] == ROLE_SYSTEM
    assert mem["history"][0]["content"] == data["initialCard"]
    assert mem["persona"]["name"] == "Jasmine"
    assert mem["persona"]["patient_name"] == "Sophia"
    assert data["personaName"] == "Jasmine"


def test_init_session_counts_persona_once_per_session():
    sid = "test-sid-persona-count"
    user_id = "doctor@example.com"
    MEMORY_STORE.pop(sid, None)
    MEMORY_STORE.pop(persona_counts_key(user_id), None)
    MEMORY_STORE.pop(persona_counted_key(user_id, sid), None)

    payload = {
        "sessionId": sid,
        "personaId": "Jasmine",
        "userInfo": {"identifier": user_id},
    }

    assert client.post("/session", json=payload).status_code == 200
    assert client.post("/session", json=payload).status_code == 200

    counts = MEMORY_STORE.get(persona_counts_key(user_id))["counts"]
    assert counts["Jasmine"] == 1

def test_init_session_persists_across_calls():
    sid = "test-sid-persist"
    MEMORY_STORE.pop(sid, None)
    
    # First call with persona
    client.post("/session", json={"sessionId": sid, "personaId": "Jasmine"})
    
    # Second call (e.g. refresh)
    response = client.post("/session", json={"sessionId": sid})
    data = response.json()
    
    assert data["character"] is not None
    assert "Jasmine" in data["character"]
    assert "Jasmine" in data["initialCard"]
    
    # Verify no duplicate history entries in memory store
    mem = MEMORY_STORE[sid]
    assert len(mem["history"]) == 1

def test_init_session_does_not_reseed_if_history_exists():
    sid = "test-sid-no-reseed"
    MEMORY_STORE.pop(sid, None)
    
    # Initialize session
    client.post("/session", json={"sessionId": sid, "personaId": "Jasmine"})
    
    # Add a user message to history
    mem = MEMORY_STORE[sid]
    mem["history"].append({"role": "user", "content": "Hello"})
    mem["full_history"].append({"role": "user", "content": "Hello"})
    assert len(mem["history"]) == 2
    
    # Re-initialize (e.g. page refresh)
    response = client.post("/session", json={"sessionId": sid})
    assert response.status_code == 200
    
    # Verify history is still length 2 (not reset or re-seeded)
    mem = MEMORY_STORE[sid]
    assert len(mem["history"]) == 2
    assert mem["history"][1]["content"] == "Hello"
    assert mem["history"][0]["role"] == ROLE_SYSTEM # Scenario card

def test_init_session_already_active():
    sid = "test-sid-active"
    conn1 = "conn-1"
    conn2 = "conn-2"
    MEMORY_STORE.pop(sid, None)
    
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


def test_init_session_can_bootstrap_non_aims_module():
    sid = "test-sid-interview-module"
    MEMORY_STORE.pop(sid, None)
    interview_module = create_interview_training_module(settings=m.settings)
    app.dependency_overrides[m.get_active_module] = lambda: interview_module
    try:
        response = client.post("/session", json={"sessionId": sid})
    finally:
        app.dependency_overrides.pop(m.get_active_module, None)

    assert response.status_code == 200
    data = response.json()
    assert data["moduleId"] == "interview"
    assert data["personaName"] == "Hiring Manager"
    assert data["transport"]["artifactKind"] == "interview_brief"
    assert MEMORY_STORE[sid]["module_id"] == "interview"
