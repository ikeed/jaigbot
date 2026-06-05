import json
import logging
import datetime
import subprocess
from typing import Dict, Any, Iterable, Optional
from google.cloud import storage
from app.config import settings
from app.chat_roles import ROLE_ASSISTANT, ROLE_COACH, ROLE_SYSTEM, ROLE_USER

logger = logging.getLogger(__name__)

# Cache git hash once at startup
try:
    GIT_HASH = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('ascii').strip()
except Exception as e:
    logger.debug("Git hash lookup failed: %s", e)
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
            except Exception as e:
                logger.error(f"Failed to initialize GCS bucket {self.bucket_name}: {e}")
        return self._bucket

    @property
    def reports_bucket(self) -> Optional[storage.Bucket]:
        if not self.reports_bucket_name:
            return None
        if self._reports_bucket is None:
            try:
                self._reports_bucket = self.client.bucket(self.reports_bucket_name)
            except Exception as e:
                logger.error(f"Failed to initialize GCS reports bucket {self.reports_bucket_name}: {e}")
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
        except Exception as e:
            logger.error(f"Failed to upload session {session_id} to GCS: {e}", exc_info=True)
            return False

    @staticmethod
    def _transform_to_logical_schema(session_id: str, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert messy internal memory to structured logical schema."""
        started_at = data.get("session_started")
        ended_at = data.get("session_ended") or data.get("updated")

        duration = None
        if started_at is not None and ended_at is not None:
            try:
                duration = round(float(ended_at) - float(started_at), 2)
            except (TypeError, ValueError):
                logger.warning("Could not calculate duration: started_at=%s, ended_at=%s", started_at, ended_at)
                duration = None

        def iso(ts):
            if ts is None:
                return None
            try:
                return datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            except (TypeError, ValueError):
                logger.warning("Could not format ISO timestamp: %s", ts)
                return None

        # Re-group transcript into turns
        transcript = []
        full_hist = data.get("full_history") or []

        # Scan in order and keep visible roles. The live UI renders each turn as
        # user -> coach -> assistant, so archives should preserve that order too.
        current_turn = 0
        for entry in full_hist:
            role = (entry.get("role") or ROLE_ASSISTANT).lower().strip()
            if role == ROLE_SYSTEM:
                transcript.append({
                    "turn": current_turn,
                    "role": ROLE_SYSTEM,
                    "content": entry.get("content"),
                    "timestamp": iso(entry.get("time"))
                })
            elif role == ROLE_USER:
                current_turn += 1
                transcript.append({
                    "turn": current_turn,
                    "role": ROLE_USER,
                    "content": entry.get("content"),
                    "timestamp": iso(entry.get("time"))
                })
            elif role == ROLE_ASSISTANT:
                transcript.append({
                    "turn": current_turn,
                    "role": ROLE_ASSISTANT,
                    "content": entry.get("content"),
                    "timestamp": iso(entry.get("time")),
                    "coaching": None
                })
            elif role == ROLE_COACH:
                coaching_data = entry.get("coaching_data")
                coaching = None
                if coaching_data:
                    coaching = {
                        **coaching_data,
                        "timestamp": iso(entry.get("time"))
                    }
                transcript.append({
                    "turn": current_turn,
                    "role": ROLE_COACH,
                    "content": entry.get("content"),
                    "timestamp": iso(entry.get("time")),
                    "coaching": coaching,
                })

        metadata = {
            "sessionId": session_id,
            "userId": user_id,
            "gitHash": GIT_HASH,
            "timestamps": {
                "startedAt": iso(started_at),
                "endedAt": iso(ended_at),
                "durationSeconds": duration
            },
            "outcome": {
                "isGameOver": data.get("game_over", False),
                "exitContext": "bug_report" if "error_report" in data else "completion" if data.get("game_over") else "abandoned",
                "report": {
                    "reason": data.get("error_report"),
                    "reportedAt": data.get("reported_at")
                } if "error_report" in data else None
            }
        }

        # Filter out persona/config
        config = {
            "persona": {
                "id": (data.get("persona") or {}).get("id") if isinstance(data.get("persona"), dict) else None,
                "name": (data.get("persona") or {}).get("name") if isinstance(data.get("persona"), dict) else None,
                "character": data.get("character"),
                "scene": data.get("scene")
            },
            "model": {
                "id": settings.MODEL_ID,
                "region": settings.REGION
            }
        }

        # Analytics
        aims_metrics = data.get("aims") or {}
        analytics = {
            "aims": {
                "totalTurns": aims_metrics.get("totalTurns"),
                "perStepCounts": aims_metrics.get("perStepCounts"),
                "runningAverage": aims_metrics.get("runningAverage")
            },
            "conversationState": data.get("aims_state"),
            "summary": data.get("coach_post")
        }

        return {
            "metadata": metadata,
            "environment": {
                "appEnv": settings.APP_ENV,
                "gcsObjectPrefix": settings.gcs_object_prefix,
            },
            "config": config,
            "transcript": transcript,
            "analytics": analytics
        }

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
        except Exception as e:
            logger.error(f"Failed to download session {session_id} from GCS: {e}")
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
                    except Exception as e:
                        logger.debug("Failed to download or parse blob %s: %s", getattr(blob, "name", "unknown"), e)
                        continue
                    persona_name = extract_persona_name_from_archive(data)
                    if persona_name in counts:
                        counts[persona_name] += 1
            logger.info("Finished GCS persona count for user %s. Processed %d blobs.", user_id, count)
        except Exception as e:
            logger.warning("Failed to count personas for user %s from GCS: %s", user_id, e)
        return counts

# Global instance
storage_service = StorageService()
