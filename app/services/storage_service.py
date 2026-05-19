import json
import logging
import datetime
import subprocess
from typing import Dict, Any, Optional
from google.cloud import storage
from app.config import settings

logger = logging.getLogger(__name__)

# Cache git hash once at startup
try:
    GIT_HASH = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('ascii').strip()
except Exception:
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
        Path: sessions/v1/user_id={user_id}/session_id={session_id}.json
        """
        target_bucket_name = self.reports_bucket_name if is_report else self.bucket_name
        bucket = self.reports_bucket if is_report else self.bucket

        logger.info(f"Using bucket '{target_bucket_name}' for upload (is_report={is_report}).")
        if not target_bucket_name:
            logger.debug(f"Target bucket not configured (is_report={is_report}), skipping upload.")
            return False

        if not bucket:
            logger.error(f"GCS bucket object for '{target_bucket_name}' not initialized (is_report={is_report}).")
            return False

        # Transform the "messy" internal memory state into the logical archive schema
        archive_data = self._transform_to_logical_schema(session_id, user_id, session_data)

        path = f"sessions/v1/user_id={user_id}/session_id={session_id}.json"
        
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

    def _transform_to_logical_schema(self, session_id: str, user_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert messy internal memory to structured logical schema."""
        started_at = data.get("session_started")
        ended_at = data.get("session_ended") or data.get("updated")
        
        duration = None
        if started_at and ended_at:
            duration = round(ended_at - started_at, 2)

        def iso(ts):
            if not ts: return None
            return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat().replace("+00:00", "Z")

        # Re-group transcript into turns
        transcript = []
        full_hist = data.get("full_history") or []
        
        # We'll group them by scanning and looking for (user, assistant) pairs 
        # and checking if there was a preceding or inter-turn coach message.
        # Structure: user_N -> assistant_N -> coach_feedback_N
        # (Based on current mess: [coach_0, user_1, assistant_1, coach_1, user_2, assistant_2...])
        
        # Simplified: scan in order, keep roles.
        current_turn = 0
        for i, entry in enumerate(full_hist):
            role = entry.get("role")
            if role == "user":
                current_turn += 1
                transcript.append({
                    "turn": current_turn,
                    "role": "user",
                    "content": entry.get("content"),
                    "timestamp": iso(entry.get("time"))
                })
            elif role == "assistant":
                # Look for coach feedback that follows this assistant reply
                coaching = None
                if i + 1 < len(full_hist) and full_hist[i+1].get("role") == "coach":
                    coach_entry = full_hist[i+1]
                    # If we have structured data, use it; otherwise fall back to content string
                    coaching_data = coach_entry.get("coaching_data")
                    if coaching_data:
                        coaching = {
                            **coaching_data,
                            "timestamp": iso(coach_entry.get("time"))
                        }
                    else:
                        coaching = {
                            "feedback": coach_entry.get("content"),
                            "timestamp": iso(coach_entry.get("time"))
                        }
                
                transcript.append({
                    "turn": current_turn,
                    "role": "assistant",
                    "content": entry.get("content"),
                    "timestamp": iso(entry.get("time")),
                    "coaching": coaching
                })
            elif role == "coach":
                # If it's the very first message (pre-intro)
                if current_turn == 0:
                     transcript.append({
                        "turn": 0,
                        "role": "coach",
                        "content": entry.get("content"),
                        "timestamp": iso(entry.get("time"))
                    })
                # Otherwise it's feedback that was already handled by the "assistant" logic above
                continue

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
            "config": config,
            "transcript": transcript,
            "analytics": analytics
        }

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
