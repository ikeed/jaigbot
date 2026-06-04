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
def test_storage_service_duration_calculation_edge_cases():
    """Test that _transform_to_logical_schema handles duration calculation edge cases."""
    service = StorageService(bucket_name="test-bucket")
    
    # Case 1: Started at 0 (should be treated as a valid number, not falsy)
    data_zero = {
        "session_started": 0,
        "session_ended": 60,
        "full_history": []
    }
    result = service._transform_to_logical_schema("sid", "uid", data_zero)
    assert result["metadata"]["timestamps"]["durationSeconds"] == 60.0
    # Case 2: One value is None
    data_none = {
        "session_started": 100,
        "session_ended": None,
        "full_history": []
    }
    result = service._transform_to_logical_schema("sid", "uid", data_none)
    assert result["metadata"]["timestamps"]["durationSeconds"] is None
    # Case 3: Values are non-numeric strings (should be handled by try-except)
    data_strings = {
        "session_started": "not-a-number",
        "session_ended": "100",
        "full_history": []
    }
    result = service._transform_to_logical_schema("sid", "uid", data_strings)
    assert result["metadata"]["timestamps"]["durationSeconds"] is None
    # Case 4: Values are numeric strings
    data_numeric_strings = {
        "session_started": "100.5",
        "session_ended": "200.5",
        "full_history": []
    }
    result = service._transform_to_logical_schema("sid", "uid", data_numeric_strings)
    assert result["metadata"]["timestamps"]["durationSeconds"] == 100.0
def test_storage_service_error_handling(mock_storage_client):
    service = StorageService(bucket_name="test-bucket")
    
    mock_bucket = MagicMock()
    service._bucket = mock_bucket
    mock_bucket.blob.side_effect = Exception("Upload failed")
    
    result = service.upload_session("sid", "uid", {"data": "test"})
    assert result is False


def test_storage_service_returns_false_when_bucket_initialization_fails(monkeypatch):
    service = StorageService(bucket_name="test-bucket")
    mock_client = MagicMock()
    mock_client.bucket.side_effect = RuntimeError("permission denied")
    service._client = mock_client

    assert service.bucket is None
    assert service.upload_session("sid", "uid", {"data": "test"}) is False


def test_storage_service_reports_bucket_uses_reports_bucket_name(monkeypatch):
    service = StorageService(bucket_name="session-bucket")
    service.reports_bucket_name = "reports-bucket"
    report_bucket = MagicMock()
    report_blob = MagicMock()
    report_bucket.blob.return_value = report_blob
    service._reports_bucket = report_bucket

    assert service.upload_session("sid", "uid", {"full_history": []}, is_report=True) is True

    report_bucket.blob.assert_called_once_with(
        "env=local/sessions/v1/user_id=uid/session_id=sid.json"
    )
    report_blob.upload_from_string.assert_called_once()


def test_storage_service_download_session_handles_missing_and_legacy_prod_path(monkeypatch):
    service = StorageService(bucket_name="test-bucket")
    bucket = MagicMock()
    current_blob = MagicMock()
    legacy_blob = MagicMock()
    bucket.blob.side_effect = [current_blob, legacy_blob]
    current_blob.exists.return_value = False
    legacy_blob.exists.return_value = True
    legacy_blob.download_as_string.return_value = b'{"ok": true}'
    service._bucket = bucket
    monkeypatch.setattr("app.services.storage_service.settings.APP_ENV", "prod")

    assert service.download_session("sid", "uid") == {"ok": True}
    assert bucket.blob.call_args_list[0].args == (
        "env=prod/sessions/v1/user_id=uid/session_id=sid.json",
    )
    assert bucket.blob.call_args_list[1].args == (
        "sessions/v1/user_id=uid/session_id=sid.json",
    )


def test_storage_service_download_session_returns_none_on_blob_error():
    service = StorageService(bucket_name="test-bucket")
    bucket = MagicMock()
    blob = MagicMock()
    bucket.blob.return_value = blob
    blob.exists.side_effect = RuntimeError("gcs down")
    service._bucket = bucket

    assert service.download_session("sid", "uid") is None


def test_storage_service_count_personas_handles_blob_parse_errors_and_cap(monkeypatch):
    service = StorageService(bucket_name="test-bucket")
    service._bucket = MagicMock()

    bad_blob = MagicMock(name="bad_blob")
    bad_blob.name = "bad.json"
    bad_blob.download_as_string.side_effect = ValueError("bad json")

    ignored_blob = MagicMock(name="ignored_blob")
    ignored_blob.name = "notes.txt"

    good_blob = MagicMock(name="good_blob")
    good_blob.name = "good.json"
    good_blob.download_as_string.return_value = b'{"persona": {"name": "Jasmine"}}'

    client = MagicMock()
    client.list_blobs.return_value = [bad_blob, ignored_blob, good_blob]
    service._client = client
    monkeypatch.setattr(
        "app.services.persona_service.extract_persona_name_from_archive",
        lambda data: data.get("persona", {}).get("name"),
    )

    assert service.count_personas_for_user("uid", ["Jasmine", "Sophia"]) == {
        "Jasmine": 1,
        "Sophia": 0,
    }


def test_storage_service_count_personas_returns_zero_counts_on_list_failure():
    service = StorageService(bucket_name="test-bucket")
    service._bucket = MagicMock()
    client = MagicMock()
    client.list_blobs.side_effect = RuntimeError("list failed")
    service._client = client

    assert service.count_personas_for_user("uid", ["Jasmine"]) == {"Jasmine": 0}
