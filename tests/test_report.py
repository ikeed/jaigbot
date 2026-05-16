import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import app
from app.services.storage_service import storage_service
from app.config import settings

client = TestClient(app)

def test_report_endpoint_success(monkeypatch):
    # Setup
    session_id = "test-session-report"
    reason = "Test reason for issue"
    user_info = {"identifier": "test@example.com"}
    
    # Mock memory store and session service
    from app.main import _MEMORY_STORE
    _MEMORY_STORE[session_id] = {
        "history": [{"role": "user", "content": "hello"}],
        "user_info": user_info,
        "updated": 123456789
    }
    
    # Mock storage service upload
    with patch("app.services.storage_service.StorageService.upload_session") as mock_upload:
        mock_upload.return_value = True
        
        response = client.post(
            "/report",
            json={
                "sessionId": session_id,
                "reason": reason,
                "userInfo": user_info
            }
        )
        
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        
        # Verify it was archived
        # Since orchestrator uses BackgroundTasks, it might not be called immediately
        # But TestClient with background tasks should execute them.
        mock_upload.assert_called_once()
        args, kwargs = mock_upload.call_args
        assert args[0] == session_id
        assert args[1] == user_info["identifier"]
        assert args[2]["error_report"] == reason
        assert args[2]["game_over"] is True
        
        # Verify session cleared from memory
        assert session_id not in _MEMORY_STORE

def test_report_endpoint_no_session(monkeypatch):
    # Mock storage download to return None
    with patch("app.services.storage_service.StorageService.download_session") as mock_down:
        mock_down.return_value = None
        response = client.post(
            "/report",
            json={
                "sessionId": "non-existent",
                "reason": "some reason"
            }
        )
        assert response.status_code == 200
        assert response.json()["message"] == "No session found to report."

def test_report_endpoint_from_gcs():
    # Setup
    session_id = "gcs-session"
    user_id = "user@gcs.com"
    reason = "Report from GCS"
    
    # Ensure not in memory
    from app.main import _MEMORY_STORE
    _MEMORY_STORE.pop(session_id, None)
    
    # Mock storage
    with patch("app.services.storage_service.StorageService.download_session") as mock_down:
        mock_down.return_value = {"history": [], "user_info": {"identifier": user_id}}
        with patch("app.services.storage_service.StorageService.upload_session") as mock_up:
            response = client.post(
                "/report",
                json={
                    "sessionId": session_id,
                    "reason": reason,
                    "userInfo": {"identifier": user_id}
                }
            )
            
            assert response.status_code == 200
            mock_down.assert_called_once_with(session_id, user_id)
            mock_up.assert_called_once()
            args, _ = mock_up.call_args
            assert args[2]["error_report"] == reason

def test_report_endpoint_invalid_body():
    response = client.post(
        "/report",
        json={
            "reason": "missing sessionId"
        }
    )
    assert response.status_code == 422 # Validation error
