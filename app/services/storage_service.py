import json
import logging
import datetime
from typing import Dict, Any, Optional
from google.cloud import storage
from app.config import settings

logger = logging.getLogger(__name__)

class StorageService:
    """
    Service for archiving session data to Google Cloud Storage.
    """

    def __init__(self, bucket_name: Optional[str] = None):
        self.bucket_name = bucket_name or settings.SESSIONS_BUCKET_NAME
        self._client: Optional[storage.Client] = None
        self._bucket: Optional[storage.Bucket] = None

    @property
    def client(self) -> storage.Client:
        if self._client is None:
            self._client = storage.Client(project=settings.PROJECT_ID)
        return self._client

    @property
    def bucket(self) -> Optional[storage.Bucket]:
        if not self.bucket_name:
            return None
        if self._bucket is None:
            try:
                self._bucket = self.client.bucket(self.bucket_name)
            except Exception as e:
                logger.error(f"Failed to initialize GCS bucket {self.bucket_name}: {e}")
        return self._bucket

    def upload_session(self, session_id: str, user_id: str, session_data: Dict[str, Any]) -> bool:
        """
        Uploads session data to GCS.
        Path: sessions/v1/user_id={user_id}/session_id={session_id}.json
        """
        if not self.bucket_name:
            logger.debug("SESSIONS_BUCKET_NAME not configured, skipping session upload.")
            return False

        bucket = self.bucket
        if not bucket:
            logger.error("GCS bucket not available for upload.")
            return False

        # Construct the path using BigQuery-friendly partitioning
        # Sanitize user_id (email) for use in path if necessary, 
        # but GCS and BQ handle equals signs and emails fine in hive-style paths.
        path = f"sessions/v1/user_id={user_id}/session_id={session_id}.json"
        
        try:
            blob = bucket.blob(path)
            
            # Add some additional metadata to the wrapper if not already present
            if "exported_at" not in session_data:
                session_data["exported_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            
            payload = json.dumps(session_data, indent=2)
            blob.upload_from_string(payload, content_type="application/json")
            
            logger.info(f"Successfully archived session {session_id} for user {user_id} to {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to upload session {session_id} to GCS: {e}", exc_info=True)
            return False

    def download_session(self, session_id: str, user_id: str) -> Optional[dict]:
        """
        Downloads session data from GCS.
        Path: sessions/v1/user_id={user_id}/session_id={session_id}.json
        """
        if not self.bucket_name:
            return None

        bucket = self.bucket
        if not bucket:
            return None

        path = f"sessions/v1/user_id={user_id}/session_id={session_id}.json"
        try:
            blob = bucket.blob(path)
            if not blob.exists():
                return None
            
            content = blob.download_as_string()
            return json.loads(content)
        except Exception as e:
            logger.error(f"Failed to download session {session_id} from GCS: {e}")
            return None

# Global instance
storage_service = StorageService()
