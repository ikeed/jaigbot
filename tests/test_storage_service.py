import pytest
import json
from unittest.mock import MagicMock, patch
from app.services.storage_service import StorageService

@pytest.fixture
def mock_storage_client():
    with patch("google.cloud.storage.Client") as mock:
        yield mock

def test_storage_service_skips_when_no_bucket(monkeypatch):
    monkeypatch.setattr("app.config.settings.SESSIONS_BUCKET_NAME", None)
    service = StorageService(bucket_name=None)
    result = service.upload_session("sid", "uid", {"data": "test"})
    assert result is False

def test_storage_service_upload_path(mock_storage_client):
    service = StorageService(bucket_name="test-bucket")
    
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    service._bucket = mock_bucket
    mock_bucket.blob.return_value = mock_blob
    
    session_data = {"data": "test"}
    result = service.upload_session("sid", "uid@example.com", session_data)
    
    assert result is True
    # Verify path
    mock_bucket.blob.assert_called_once_with("env=local/sessions/v1/user_id=uid@example.com/session_id=sid.json")
    # Verify content was uploaded
    mock_blob.upload_from_string.assert_called_once()
    
    # Verify the payload structure follows the new logical schema
    args, kwargs = mock_blob.upload_from_string.call_args
    payload = json.loads(args[0])
    assert "metadata" in payload
    assert payload["environment"]["appEnv"] == "local"
    assert payload["metadata"]["sessionId"] == "sid"
    assert payload["metadata"]["userId"] == "uid@example.com"
    assert "persona" in payload["config"]
    assert "config" in payload
    assert "transcript" in payload
    assert "analytics" in payload

def test_storage_service_structured_archive(mock_storage_client):
    service = StorageService(bucket_name="test-bucket")
    
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    service._bucket = mock_bucket
    mock_bucket.blob.return_value = mock_blob
    
    session_data = {
        "session_started": 1716000000.0,
        "updated": 1716000500.0,
        "character": "Test Character",
        "scene": "Test Scene",
        "persona": {"id": 99, "name": "Test Persona"},
        "full_history": [
            {"role": "system", "content": "Person: Test\nBackground: Brief", "time": 1716000001.0},
            {"role": "user", "content": "Hello", "time": 1716000100.0},
            {
                "role": "coach", 
                "content": "Coach string", 
                "time": 1716000101.0,
                "coaching_data": {
                    "step": "Announce",
                    "score": 3,
                    "reasons": ["Good job"],
                    "tips": ["Keep it up"],
                    "phase": "Announce"
                }
            },
            {"role": "assistant", "content": "Hi there", "time": 1716000200.0},
        ],
        "aims": {
            "totalTurns": 1,
            "perStepCounts": {"Announce": 1},
            "runningAverage": {"Announce": 3.0}
        },
        "coach_post": {
            "title": "Nice job!",
            "lines": ["Line 1", "Line 2"]
        },
        "game_over": True
    }
    
    result = service.upload_session("sid", "uid@example.com", session_data)
    assert result is True
    
    args, kwargs = mock_blob.upload_from_string.call_args
    payload = json.loads(args[0])

    system_entry = next(t for t in payload["transcript"] if t["role"] == "system")
    assert system_entry["turn"] == 0
    assert "Person: Test" in system_entry["content"]
    
    # Verify transcript preserves visible order and structured coaching
    roles = [t["role"] for t in payload["transcript"]]
    assert roles == ["system", "user", "coach", "assistant"]
    turn1_coach = next(t for t in payload["transcript"] if t["role"] == "coach")
    assert turn1_coach["turn"] == 1
    assert turn1_coach["coaching"]["step"] == "Announce"
    assert turn1_coach["coaching"]["score"] == 3
    assert "Keep it up" in turn1_coach["coaching"]["tips"]
    
    # Verify analytics has summary (coach_post)
    assert payload["analytics"]["summary"]["title"] == "Nice job!"
    assert "Line 1" in payload["analytics"]["summary"]["lines"]
    
    # Verify metadata outcome
    assert payload["metadata"]["outcome"]["isGameOver"] is True
    assert payload["metadata"]["outcome"]["exitContext"] == "completion"
    assert payload["config"]["persona"]["id"] == 99
    assert payload["config"]["persona"]["name"] == "Test Persona"
def test_storage_service_error_handling(mock_storage_client):
    service = StorageService(bucket_name="test-bucket")
    
    mock_bucket = MagicMock()
    service._bucket = mock_bucket
    mock_bucket.blob.side_effect = Exception("Upload failed")
    
    result = service.upload_session("sid", "uid", {"data": "test"})
    assert result is False
