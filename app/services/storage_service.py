import json
import logging
import subprocess
from typing import Dict, Any, Iterable, Optional
from google.cloud import storage
from app.config import settings
from app.core.archive_serialization import serialize_archive_envelope
from app.core.legacy_module_resolution import resolve_archive_module_id
from app.core.module_runtime import get_builtin_active_module

logger = logging.getLogger(__name__)

# Cache git hash once at startup
try:
    GIT_HASH = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('ascii').strip()
except Exception as exc:
    logger.debug("Git hash lookup failed: %s", exc)
    GIT_HASH = "unknown"

class StorageService:
    """
    Service for archiving session data to Google Cloud Storage.
    """

    def __init__(self, bucket_name: Optional[str] = None):
        self.bucket_name = bucket_name or settings.SESSIONS_BUCKET_NAME
        self.reports_bucket_name = settings.REPORTS_BUCKET_NAME
        self._client: Optional[storage.Client] = None
        self._bucket: Optional[storage.Bucket] = None
        self._reports_bucket: Optional[storage.Bucket] = None

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
            except Exception as bucket_exc:
                logger.error(f"Failed to initialize GCS bucket {self.bucket_name}: {bucket_exc}")
        return self._bucket

    @property
    def reports_bucket(self) -> Optional[storage.Bucket]:
        if not self.reports_bucket_name:
            return None
        if self._reports_bucket is None:
            try:
                self._reports_bucket = self.client.bucket(self.reports_bucket_name)
            except Exception as reports_bucket_exc:
                logger.error(f"Failed to initialize GCS reports bucket {self.reports_bucket_name}: {reports_bucket_exc}")
        return self._reports_bucket

    def upload_session(self, session_id: str, user_id: str, session_data: Dict[str, Any], is_report: bool = False) -> bool:
        """
        Uploads session data to GCS.
        Path: env={APP_ENV}/sessions/v1/user_id={user_id}/session_id={session_id}.json
        """
        target_bucket_name = self.reports_bucket_name if is_report else self.bucket_name
        bucket = self.reports_bucket if is_report else self.bucket

        logger.info(f"Using bucket '{target_bucket_name}' for upload (is_report={is_report}).")
        if not target_bucket_name:
            logger.debug(f"Target bucket not configured (is_report={is_report}), skipping upload.")
            return False

        if not bucket:
            logger.error(f"GCS bucket {target_bucket_name} not available for upload.")
            return False

        # Transform the "messy" internal memory state into the logical archive schema
        archive_data = self._transform_to_logical_schema(session_id, user_id, session_data)

        path = settings.gcs_path("sessions/v1", f"user_id={user_id}", f"session_id={session_id}.json")
        
        try:
            blob = bucket.blob(path)
            payload = json.dumps(archive_data, indent=2)
            logger.info(f"Attempting GCS upload to bucket='{target_bucket_name}' path='{path}'")
            blob.upload_from_string(payload, content_type="application/json")
            
            logger.info(f"Successfully archived session {session_id} for user {user_id} to {path}")
            return True
        except Exception as upload_exc:
            logger.error(f"Failed to upload session {session_id} to GCS: {upload_exc}", exc_info=True)
            return False

    @staticmethod
    def _transform_to_logical_schema(session_id: str, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert internal memory to a module-aware logical archive schema."""
        persisted_module_id = StorageService._resolve_module_id_for_archive_build(data)
        active_module = get_builtin_active_module(active_module_id=persisted_module_id)
        envelope = active_module.build_archive_envelope(
            session_id=session_id,
            user_id=user_id,
            data=data,
            git_hash=GIT_HASH,
            settings=settings,
        )
        return serialize_archive_envelope(envelope)

    @staticmethod
    def _resolve_module_id_for_archive_build(data: Dict[str, Any]) -> str:
        """Resolve module ownership for archive serialization.

        Current live session memory may still rely on the deployment's active
        module when it does not persist a `module_id` yet. Structured
        archive-shaped payloads are stricter: if they look like archives but do
        not carry a resolvable module identity, refuse to guess.
        """
        persisted_module_id = resolve_archive_module_id(data)
        if persisted_module_id:
            return persisted_module_id
        if StorageService._looks_like_structured_archive_payload(data):
            raise ValueError("Cannot infer module_id for archive-shaped payload without explicit module metadata.")
        return settings.ACTIVE_MODULE

    @staticmethod
    def _looks_like_structured_archive_payload(data: Dict[str, Any]) -> bool:
        return any(
            key in data
            for key in (
                "metadata",
                "module",
                "environment",
                "transcript",
                "analytics",
                "config",
            )
        )

    def download_session(self, session_id: str, user_id: str) -> Optional[dict]:
        """
        Downloads session data from GCS.
        Path: env={APP_ENV}/sessions/v1/user_id={user_id}/session_id={session_id}.json
        """
        if not self.bucket_name:
            return None

        bucket = self.bucket
        if not bucket:
            return None

        path = settings.gcs_path("sessions/v1", f"user_id={user_id}", f"session_id={session_id}.json")
        try:
            blob = bucket.blob(path)
            if not blob.exists() and settings.APP_ENV == "prod":
                legacy_path = f"sessions/v1/user_id={user_id}/session_id={session_id}.json"
                blob = bucket.blob(legacy_path)
            if not blob.exists():
                return None
            
            content = blob.download_as_string()
            return json.loads(content)
        except Exception as download_exc:
            logger.error(f"Failed to download session {session_id} from GCS: {download_exc}")
            return None

    def count_personas_for_user(self, user_id: str, persona_names: Iterable[str]) -> Dict[str, int]:
        """
        Count archived sessions by persona for one user in the current APP_ENV.

        This is a backfill/source-of-truth path for the Redis persona-count cache,
        so failures return zero counts rather than blocking scenario startup.
        """
        counts = {str(name): 0 for name in persona_names}
        if not self.bucket_name or not user_id:
            return counts

        bucket = self.bucket
        if not bucket:
            return counts

        prefixes = [settings.gcs_path("sessions/v1", f"user_id={user_id}") + "/"]
        if settings.APP_ENV == "prod":
            prefixes.append(f"sessions/v1/user_id={user_id}/")

        try:
            from app.services.persona_service import extract_persona_name_from_archive

            logger.info("Starting GCS persona count for user %s", user_id)
            count = 0
            for prefix in prefixes:
                for blob in self.client.list_blobs(self.bucket_name, prefix=prefix):
                    count += 1
                    if count > 100: # Safety cap
                        logger.warning("User %s has >100 sessions, capping count", user_id)
                        break
                    if not str(getattr(blob, "name", "")).endswith(".json"):
                        continue
                    try:
                        data = json.loads(blob.download_as_string())
                    except Exception as blob_exc:
                        logger.debug("Failed to download or parse blob %s: %s", getattr(blob, "name", "unknown"), blob_exc)
                        continue
                    persona_name = extract_persona_name_from_archive(data)
                    if persona_name in counts:
                        counts[persona_name] += 1
            logger.info("Finished GCS persona count for user %s. Processed %d blobs.", user_id, count)
        except Exception as count_exc:
            logger.warning("Failed to count personas for user %s from GCS: %s", user_id, count_exc)
        return counts

# Global instance
storage_service = StorageService()
