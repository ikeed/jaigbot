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
    mock_index_blob = MagicMock()
    mock_index_blob.download_as_string.side_effect = ValueError("no index yet")
    service._bucket = mock_bucket

    def _blob_side_effect(path):
        return mock_index_blob if path.endswith("_persona_index.json") else mock_blob

    mock_bucket.blob.side_effect = _blob_side_effect

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
    
    result = service.upload_session("sid", "uid@example.com", session_data, finalize_persona_index=True)
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

    # Verify the persona index was updated with this session's persona and stats
    mock_bucket.blob.assert_any_call("env=local/sessions/v1/user_id=uid@example.com/_persona_index.json")
    index_args, _ = mock_index_blob.upload_from_string.call_args
    index_payload = json.loads(index_args[0])
    assert index_payload["entries"] == [{
        "persona": "Test Persona",
        "session_id": "sid",
        "number_of_turns": 1,
        "outcome": None,
        "overall_score": 25,
        "announce_score": 3.0,
        "inquire_score": None,
        "mirror_score": None,
        "secure_score": None,
        "ts": index_payload["entries"][0]["ts"],
    }]
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


def test_storage_service_count_personas_reads_index(monkeypatch):
    service = StorageService(bucket_name="test-bucket")
    bucket = MagicMock()
    index_blob = MagicMock()
    index_blob.download_as_string.return_value = json.dumps({
        "entries": [
            {"persona": "Jasmine", "ts": 1.0},
            {"persona": "Jasmine", "ts": 2.0},
            {"persona": "Unknown Persona", "ts": 3.0},
        ]
    }).encode("utf-8")
    bucket.blob.return_value = index_blob
    service._bucket = bucket

    assert service.count_personas_for_user("uid", ["Jasmine", "Sophia"]) == {
        "Jasmine": 2,
        "Sophia": 0,
    }
    bucket.blob.assert_called_once_with("env=local/sessions/v1/user_id=uid/_persona_index.json")


def test_storage_service_count_personas_returns_zero_when_index_missing():
    service = StorageService(bucket_name="test-bucket")
    bucket = MagicMock()
    index_blob = MagicMock()
    index_blob.download_as_string.side_effect = FileNotFoundError("no such object")
    bucket.blob.return_value = index_blob
    service._bucket = bucket

    assert service.count_personas_for_user("uid", ["Jasmine"]) == {"Jasmine": 0}


def test_storage_service_count_personas_returns_zero_on_malformed_index():
    service = StorageService(bucket_name="test-bucket")
    bucket = MagicMock()
    index_blob = MagicMock()
    index_blob.download_as_string.return_value = b"not json"
    bucket.blob.return_value = index_blob
    service._bucket = bucket

    assert service.count_personas_for_user("uid", ["Jasmine"]) == {"Jasmine": 0}


def test_storage_service_record_persona_index_entry_appends_and_caps(monkeypatch):
    from app.services import storage_service as storage_service_module

    monkeypatch.setattr(storage_service_module, "PERSONA_INDEX_MAX_ENTRIES", 2)
    service = StorageService(bucket_name="test-bucket")
    bucket = MagicMock()
    index_blob = MagicMock()
    index_blob.download_as_string.return_value = json.dumps({
        "entries": [{"persona": "Jasmine", "ts": 1.0}, {"persona": "Jasmine", "ts": 2.0}]
    }).encode("utf-8")
    bucket.blob.return_value = index_blob
    service._bucket = bucket

    service._record_persona_index_entry("uid", "sid-new", {"config": {"persona": {"name": "Sophia"}}})

    args, _ = index_blob.upload_from_string.call_args
    entries = json.loads(args[0])["entries"]
    assert [e["persona"] for e in entries] == ["Jasmine", "Sophia"]
    assert entries[-1]["session_id"] == "sid-new"
    assert entries[-1]["number_of_turns"] == 0
    assert entries[-1]["outcome"] is None
    assert entries[-1]["overall_score"] is None


def test_storage_service_record_persona_index_entry_skips_when_no_persona():
    service = StorageService(bucket_name="test-bucket")
    bucket = MagicMock()
    service._bucket = bucket

    service._record_persona_index_entry("uid", "sid", {"config": {"persona": {}}})

    bucket.blob.assert_not_called()


def test_storage_service_record_persona_index_entry_overwrites_matching_session_id(monkeypatch):
    service = StorageService(bucket_name="test-bucket")
    bucket = MagicMock()
    index_blob = MagicMock()
    index_blob.download_as_string.return_value = json.dumps({
        "entries": [
            {"persona": "Jasmine", "session_id": "sid-open", "outcome": "open", "ts": 1.0},
            {"persona": "Sophia", "session_id": "sid-other", "outcome": "vaccination", "ts": 2.0},
        ]
    }).encode("utf-8")
    bucket.blob.return_value = index_blob
    service._bucket = bucket

    service._record_persona_index_entry(
        "uid", "sid-open", {"config": {"persona": {"name": "Jasmine"}}, "metadata": {"outcome": {"exitContext": "abandoned"}}}
    )

    args, _ = index_blob.upload_from_string.call_args
    entries = json.loads(args[0])["entries"]
    # Same number of entries: the "open" row was overwritten in place, not duplicated.
    assert len(entries) == 2
    updated = next(e for e in entries if e["session_id"] == "sid-open")
    assert updated["outcome"] == "abandoned"
    assert next(e for e in entries if e["session_id"] == "sid-other")["outcome"] == "vaccination"


def test_storage_service_record_open_session_appends_open_row():
    service = StorageService(bucket_name="test-bucket")
    bucket = MagicMock()
    index_blob = MagicMock()
    index_blob.download_as_string.side_effect = ValueError("no index yet")
    bucket.blob.return_value = index_blob
    service._bucket = bucket

    service.record_open_session("uid", "sid-1", "Jasmine")

    args, _ = index_blob.upload_from_string.call_args
    entries = json.loads(args[0])["entries"]
    assert entries == [{
        "persona": "Jasmine",
        "session_id": "sid-1",
        "number_of_turns": 0,
        "outcome": "open",
        "overall_score": None,
        "announce_score": None,
        "inquire_score": None,
        "mirror_score": None,
        "secure_score": None,
        "ts": entries[0]["ts"],
    }]


def test_storage_service_record_open_session_skips_when_no_persona():
    service = StorageService(bucket_name="test-bucket")
    bucket = MagicMock()
    service._bucket = bucket

    service.record_open_session("uid", "sid-1", None)

    bucket.blob.assert_not_called()


def test_storage_service_upload_session_does_not_touch_persona_index_by_default(mock_storage_client):
    """Per-turn writes must not call finalize_persona_index=True implicitly -
    only prune_expired()/handle_report opt in, or every turn would spam a
    duplicate/overwrite of the persona index."""
    service = StorageService(bucket_name="test-bucket")
    bucket = MagicMock()
    session_blob = MagicMock()
    bucket.blob.return_value = session_blob
    service._bucket = bucket

    session_data = {"config": {"persona": {"name": "Jasmine"}}, "persona": {"name": "Jasmine"}}
    assert service.upload_session("sid", "uid", session_data) is True

    bucket.blob.assert_called_once_with("env=local/sessions/v1/user_id=uid/session_id=sid.json")


@pytest.mark.parametrize(
    "session_data,expected_exit_context",
    [
        ({}, "open"),
        ({"game_over": False}, "open"),
        ({"exit_context": "abandoned"}, "abandoned"),
        ({"game_over": True}, "completion"),
        ({"error_report": "bad reply"}, "bug_report"),
        # game_over wins over an abandoned override (a session that completed
        # then went stale is a completion, not an abandonment).
        ({"game_over": True, "exit_context": "abandoned"}, "completion"),
    ],
)
def test_storage_service_transform_exit_context(session_data, expected_exit_context):
    service = StorageService(bucket_name="test-bucket")
    result = service._transform_to_logical_schema("sid", "uid", {**session_data, "full_history": []})
    assert result["metadata"]["outcome"]["exitContext"] == expected_exit_context


@pytest.mark.parametrize(
    "archive_data,expected_outcome",
    [
        ({"metadata": {"outcome": {"exitContext": "bug_report"}}}, "bug_report"),
        ({"metadata": {"outcome": {"exitContext": "abandoned"}}}, "abandoned"),
        ({"metadata": {"outcome": {"exitContext": "open"}}}, "open"),
        ({"analytics": {"summary": {"outcome": "accepted_vaccine"}}}, "vaccination"),
        ({"analytics": {"summary": {"outcome": "accepted_literature"}}}, "literature"),
        ({"analytics": {"summary": {"outcome": "deferred"}}}, None),
        ({}, None),
    ],
)
def test_storage_service_derive_index_outcome(archive_data, expected_outcome):
    assert StorageService._derive_index_outcome(archive_data) == expected_outcome


def test_storage_service_build_persona_index_entry_includes_turns_and_scores():
    archive_data = {
        "transcript": [
            {"role": "system", "content": "card"},
            {"role": "user", "content": "hi"},
            {"role": "coach", "content": "coach note"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second turn"},
        ],
        "analytics": {
            "aims": {
                "runningAverage": {
                    "Announce": 3.0,
                    "Inquire": 2.0,
                    "Mirror": 1.5,
                    "Secure": 0.0,
                }
            },
            "summary": {"outcome": "accepted_vaccine"},
        },
        "metadata": {"outcome": {"exitContext": "completion"}},
    }

    entry = StorageService._build_persona_index_entry("sid-123", "Jasmine", archive_data)

    assert entry["session_id"] == "sid-123"
    assert entry["persona"] == "Jasmine"
    assert entry["number_of_turns"] == 2
    assert entry["outcome"] == "vaccination"
    assert entry["announce_score"] == 3.0
    assert entry["inquire_score"] == 2.0
    assert entry["mirror_score"] == 1.5
    assert entry["secure_score"] == 0.0
    assert entry["overall_score"] == 54
    assert isinstance(entry["ts"], float)
