import pytest
from unittest.mock import MagicMock, patch
from app.services.storage_service import StorageService

@pytest.fixture
def mock_storage_client():
    with patch("google.cloud.storage.Client") as mock:
        yield mock

def test_storage_service_skips_when_no_bucket():
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
    mock_bucket.blob.assert_called_once_with("sessions/v1/user_id=uid@example.com/session_id=sid.json")
    # Verify content was uploaded
    mock_blob.upload_from_string.assert_called_once()
    
    # Check that session_data was enriched
    assert "exported_at" in session_data

def test_storage_service_error_handling(mock_storage_client):
    service = StorageService(bucket_name="test-bucket")
    
    mock_bucket = MagicMock()
    service._bucket = mock_bucket
    mock_bucket.blob.side_effect = Exception("Upload failed")
    
    result = service.upload_session("sid", "uid", {"data": "test"})
    assert result is False
