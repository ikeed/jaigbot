import pytest
from fastapi.testclient import TestClient
from app.main import app as fastapi_app
import json
import logging
from unittest.mock import MagicMock

def test_chat_with_user_info(monkeypatch):
    """Verify that userInfo in ChatRequest is accepted and logged."""
    
    # Mock environment variables
    monkeypatch.setenv("PROJECT_ID", "test-project")
    monkeypatch.setenv("REGION", "us-central1")
    
    # Also monkeypatch app.main variables if they were already initialized
    import app.main
    monkeypatch.setattr(app.main, "PROJECT_ID", "test-project")
    monkeypatch.setattr(app.main, "REGION", "us-central1")
    
    # Mock Vertex call to avoid real API calls
    mock_vertex = MagicMock(return_value="Hello! I am a clinical assistant.")
    monkeypatch.setattr("app.services.vertex_helpers.vertex_call_with_fallback_text", mock_vertex)
    
    # Capture logs to verify userInfo is present
    # We catch logs from ALL loggers that might use telemetry
    log_messages = []
    
    class MockHandler(logging.Handler):
        def emit(self, record):
            log_messages.append(record.getMessage())
            
    mock_handler = MockHandler()
    root_logger = logging.getLogger()
    root_logger.addHandler(mock_handler)
    root_logger.setLevel(logging.INFO)
    
    client = TestClient(fastapi_app)
    
    user_info = {"identifier": "test@example.com", "metadata": {"name": "Test User"}}
    payload = {
        "message": "Hello",
        "sessionId": "test-session",
        "userInfo": user_info
    }
    
    response = client.post("/chat", json=payload)
    
    assert response.status_code == 200
    assert "reply" in response.json()
    
    # Check if any log message contains the userInfo
    found_user_info = False
    for msg in log_messages:
        if "test@example.com" in msg:
            found_user_info = True
            break
            
    assert found_user_info, f"UserInfo not found in logs. Captured logs: {log_messages}"
    
    root_logger.removeHandler(mock_handler)

if __name__ == "__main__":
    pytest.main([__file__])
