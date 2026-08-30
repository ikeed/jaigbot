import datetime
import json
import logging
import time
from collections.abc import Iterable
from typing import Any

from google.cloud import storage

from app.chat_roles import ROLE_ASSISTANT, ROLE_COACH, ROLE_SYSTEM, ROLE_USER
from app.config import settings

logger = logging.getLogger(__name__)

# Cap on entries kept in a user's persona index (see _record_persona_index_entry).
PERSONA_INDEX_MAX_ENTRIES = 200

class StorageService:
    """
    Service for archiving session data to Google Cloud Storage.
    """

    def __init__(self, bucket_name: str | None = None):
        self.bucket_name = bucket_name or settings.SESSIONS_BUCKET_NAME
        self.reports_bucket_name = settings.REPORTS_BUCKET_NAME
        self._client: storage.Client | None = None
        self._bucket: storage.Bucket | None = None
        self._reports_bucket: storage.Bucket | None = None

    @property
    def client(self) -> storage.Client:
        if self._client is None:
            self._client = storage.Client(project=settings.PROJECT_ID)
        return self._client

    @property
    def bucket(self) -> storage.Bucket | None:
        if not self.bucket_name:
            return None
        if self._bucket is None:
            try:
                self._bucket = self.client.bucket(self.bucket_name)
            except Exception as bucket_exc:
                logger.error(f"Failed to initialize GCS bucket {self.bucket_name}: {bucket_exc}")
        return self._bucket

    @property
    def reports_bucket(self) -> storage.Bucket | None:
        if not self.reports_bucket_name:
            return None
        if self._reports_bucket is None:
            try:
                self._reports_bucket = self.client.bucket(self.reports_bucket_name)
            except Exception as reports_bucket_exc:
                logger.error(f"Failed to initialize GCS reports bucket {self.reports_bucket_name}: {reports_bucket_exc}")
        return self._reports_bucket

    def upload_session(
        self,
        session_id: str,
        user_id: str,
        session_data: dict[str, Any],
        is_report: bool = False,
        finalize_persona_index: bool = False,
    ) -> bool:
        """
        Uploads session data to GCS.
        Path: env={APP_ENV}/sessions/v1/user_id={user_id}/session_id={session_id}.json

        Called on every chat turn (open sessions included), so most calls must
        NOT touch the persona index - only a caller that knows the session has
        actually concluded (endgame sweep in prune_expired, or an explicit bug
        report) should pass finalize_persona_index=True.
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

            # The persona index always lives in the sessions bucket (see
            # _persona_index_path / self.bucket), independent of is_report -
            # reports upload their full transcript to a separate reports
            # bucket, but a reported session is still a real persona
            # interaction (with outcome "bug_report") worth indexing.
            if finalize_persona_index:
                self._record_persona_index_entry(user_id, session_id, archive_data)

            return True
        except Exception as upload_exc:
            logger.error(f"Failed to upload session {session_id} to GCS: {upload_exc}", exc_info=True)
            return False

    @staticmethod
    def _transform_to_logical_schema(session_id: str, user_id: str, data: dict[str, Any]) -> dict[str, Any]:
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
                return datetime.datetime.fromtimestamp(float(ts), datetime.UTC).isoformat().replace("+00:00", "Z")
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
            "gitHash": settings.GIT_SHA,
            "timestamps": {
                "startedAt": iso(started_at),
                "endedAt": iso(ended_at),
                "durationSeconds": duration
            },
            "outcome": {
                "isGameOver": data.get("game_over", False),
                "exitContext": (
                    "bug_report" if "error_report" in data
                    else "completion" if data.get("game_over")
                    else "abandoned" if data.get("exit_context") == "abandoned"
                    else "open"
                ),
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

    def download_session(self, session_id: str, user_id: str) -> dict | None:
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

    def _persona_index_path(self, user_id: str) -> str:
        return settings.gcs_path("sessions/v1", f"user_id={user_id}", "_persona_index.json")

    @staticmethod
    def _derive_index_outcome(archive_data: dict[str, Any]) -> str | None:
        """Map the archive's exit/resolution info down to one of
        "bug_report" | "abandoned" | "open" | "vaccination" | "literature",
        or None when the session completed without one of those resolutions."""
        exit_context = (((archive_data.get("metadata") or {}).get("outcome") or {}).get("exitContext"))
        if exit_context == "bug_report":
            return "bug_report"
        if exit_context == "abandoned":
            return "abandoned"
        if exit_context == "open":
            return "open"
        resolution_type = ((archive_data.get("analytics") or {}).get("summary") or {}).get("outcome")
        if resolution_type == "accepted_vaccine":
            return "vaccination"
        if resolution_type == "accepted_literature":
            return "literature"
        return None

    @staticmethod
    def _build_persona_index_entry(session_id: str, persona_name: str, archive_data: dict[str, Any]) -> dict[str, Any]:
        transcript = archive_data.get("transcript") or []
        number_of_turns = sum(
            1 for entry in transcript if isinstance(entry, dict) and entry.get("role") == ROLE_USER
        )

        running_average = ((archive_data.get("analytics") or {}).get("aims") or {}).get("runningAverage") or {}
        try:
            from app.services.coach_post import _overall_score_pct
            overall_score = _overall_score_pct(running_average) if isinstance(running_average, dict) else None
        except Exception:
            overall_score = None

        return {
            "persona": str(persona_name),
            "session_id": session_id,
            "number_of_turns": number_of_turns,
            "outcome": StorageService._derive_index_outcome(archive_data),
            "overall_score": overall_score,
            "announce_score": running_average.get("Announce") if isinstance(running_average, dict) else None,
            "inquire_score": running_average.get("Inquire") if isinstance(running_average, dict) else None,
            "mirror_score": running_average.get("Mirror") if isinstance(running_average, dict) else None,
            "secure_score": running_average.get("Secure") if isinstance(running_average, dict) else None,
            "ts": time.time(),
        }

    def record_open_session(self, user_id: str, session_id: str, persona_name: str | None) -> None:
        """
        Best-effort: append an "open" row to the user's persona index when a
        brand-new session is assigned a persona, so the index reflects every
        session from the moment it starts (not just ones that reach a final
        resolution). prune_expired() later finds this row by session_id and
        overwrites its outcome once the session concludes or goes stale.
        """
        if not persona_name:
            return
        self._upsert_persona_index_entry(user_id, {
            "persona": str(persona_name),
            "session_id": session_id,
            "number_of_turns": 0,
            "outcome": "open",
            "overall_score": None,
            "announce_score": None,
            "inquire_score": None,
            "mirror_score": None,
            "secure_score": None,
            "ts": time.time(),
        })

    def _record_persona_index_entry(self, user_id: str, session_id: str, archive_data: dict[str, Any]) -> None:
        """
        Best-effort upsert into a small per-user persona index, so
        count_personas_for_user can read one small object on a cache miss
        instead of listing and downloading every archived session transcript
        for that user. Failures here must never affect upload_session's
        return value, since the session archive itself already succeeded.

        Only call this once a session has truly concluded (it overwrites the
        "open" row record_open_session created at session start, matched by
        session_id, instead of appending a duplicate).
        """
        try:
            from app.services.persona_service import extract_persona_name_from_archive
            persona_name = extract_persona_name_from_archive(archive_data)
            if not persona_name:
                return

            self._upsert_persona_index_entry(
                user_id, self._build_persona_index_entry(session_id, persona_name, archive_data)
            )
        except Exception as index_exc:
            logger.debug("Failed to update persona index for user %s: %s", user_id, index_exc)

    def _upsert_persona_index_entry(self, user_id: str, entry: dict[str, Any]) -> None:
        """Write `entry` into the user's persona index, replacing any existing
        row with the same session_id in place rather than appending a duplicate."""
        try:
            bucket = self.bucket
            if not bucket:
                return

            path = self._persona_index_path(user_id)
            blob = bucket.blob(path)
            try:
                existing = json.loads(blob.download_as_string())
            except Exception:
                existing = None
            entries = existing.get("entries") if isinstance(existing, dict) else None
            if not isinstance(entries, list):
                entries = []

            session_id = entry.get("session_id")
            match_idx = next(
                (i for i, e in enumerate(entries) if isinstance(e, dict) and e.get("session_id") == session_id),
                None,
            )
            if match_idx is not None:
                entries[match_idx] = entry
            else:
                entries.append(entry)
            if len(entries) > PERSONA_INDEX_MAX_ENTRIES:
                entries = entries[-PERSONA_INDEX_MAX_ENTRIES:]

            blob.upload_from_string(json.dumps({"entries": entries}), content_type="application/json")
        except Exception as index_exc:
            logger.debug("Failed to update persona index for user %s: %s", user_id, index_exc)

    def count_personas_for_user(self, user_id: str, persona_names: Iterable[str]) -> dict[str, int]:
        """
        Count archived sessions by persona for one user in the current APP_ENV.

        Reads the small per-user persona index maintained by
        _record_persona_index_entry instead of listing and downloading every
        archived session transcript, so this stays cheap enough to run
        synchronously on a Redis persona-count cache miss (e.g. right after a
        local memory-store restart, or for any user with many archived
        sessions). Users archived before this index existed will read as
        zero counts until they get new sessions - that's an acceptable
        cold-start rather than backfilling via the full scan this replaces.
        This is a backfill/source-of-truth path for the Redis persona-count
        cache, so failures return zero counts rather than blocking scenario
        startup.
        """
        counts = {str(name): 0 for name in persona_names}
        if not self.bucket_name or not user_id:
            return counts

        bucket = self.bucket
        if not bucket:
            return counts

        try:
            blob = bucket.blob(self._persona_index_path(user_id))
            data = json.loads(blob.download_as_string())
            entries = data.get("entries") if isinstance(data, dict) else None
            if isinstance(entries, list):
                for entry in entries:
                    name = entry.get("persona") if isinstance(entry, dict) else None
                    if name in counts:
                        counts[name] += 1
        except Exception as count_exc:
            logger.debug("No persona index available for user %s (or failed to read it): %s", user_id, count_exc)
        return counts

# Global instance
storage_service = StorageService()
