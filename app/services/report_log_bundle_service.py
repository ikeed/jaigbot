from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import google.auth
from google.auth.transport.requests import AuthorizedSession

from app.config import settings

logger = logging.getLogger(__name__)


class ReportLogBundleService:
    """Collect and persist a bounded Cloud Logging slice for a reported session."""

    def __init__(
        self,
        *,
        storage_service: Any,
        settings_obj: Any = settings,
        auth_default: Callable[..., Any] | None = None,
        session_cls: Callable[[Any], Any] | None = None,
    ) -> None:
        self.storage_service = storage_service
        self.settings = settings_obj
        self._auth_default = auth_default or google.auth.default
        self._session_cls = session_cls or AuthorizedSession

    def collect_and_store_report_logs(
        self,
        *,
        session_id: str,
        user_id: str,
        reported_at: datetime,
        request_id: str | None = None,
        window_before_s: int = 20 * 60,
        window_after_s: int = 2 * 60,
    ) -> bool:
        if not self.settings.PROJECT_ID:
            logger.info("Skipping report log bundle collection for session %s: PROJECT_ID not configured.", session_id)
            return False
        if not self.settings.service_name:
            logger.info("Skipping report log bundle collection for session %s: service_name unavailable.", session_id)
            return False

        query_start = reported_at - timedelta(seconds=window_before_s)
        query_end = reported_at + timedelta(seconds=window_after_s)

        try:
            entries = self._collect_entries(
                session_id=session_id,
                query_start=query_start,
                query_end=query_end,
            )
        except Exception as exc:
            logger.warning("Failed to collect report log bundle for session %s: %s", session_id, exc)
            return False

        payload = {
            "metadata": {
                "collectorVersion": 1,
                "sessionId": session_id,
                "requestId": request_id,
                "userId": user_id,
                "serviceName": self.settings.service_name,
                "appEnv": self.settings.APP_ENV,
                "projectId": self.settings.PROJECT_ID,
                "reportedAt": _to_rfc3339(reported_at),
                "queryStart": _to_rfc3339(query_start),
                "queryEnd": _to_rfc3339(query_end),
                "matchedEventCount": len(entries),
            },
            "entries": entries,
        }
        return self.storage_service.upload_report_artifact(
            session_id=session_id,
            user_id=user_id,
            artifact_suffix="logs.json",
            payload=payload,
        )

    def _collect_entries(
        self,
        *,
        session_id: str,
        query_start: datetime,
        query_end: datetime,
    ) -> list[dict[str, Any]]:
        creds, _ = self._auth_default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = self._session_cls(creds)
        url = "https://logging.googleapis.com/v2/entries:list"
        filter_expr = self._build_filter(
            session_id=session_id,
            query_start=query_start,
            query_end=query_end,
        )

        entries: list[dict[str, Any]] = []
        next_page_token: str | None = None
        while True:
            body: dict[str, Any] = {
                "resourceNames": [f"projects/{self.settings.PROJECT_ID}"],
                "filter": filter_expr,
                "orderBy": "timestamp asc",
                "pageSize": 1000,
            }
            if next_page_token:
                body["pageToken"] = next_page_token

            response = session.post(url, json=body, timeout=30)
            response.raise_for_status()
            payload = response.json()
            entries.extend(payload.get("entries", []))
            next_page_token = payload.get("nextPageToken")
            if not next_page_token:
                break

        return entries

    def _build_filter(
        self,
        *,
        session_id: str,
        query_start: datetime,
        query_end: datetime,
    ) -> str:
        start_ts = _to_rfc3339(query_start)
        end_ts = _to_rfc3339(query_end)
        service_name = _quote_filter_value(self.settings.service_name)
        app_env = _quote_filter_value(self.settings.APP_ENV)
        session_value = _quote_filter_value(session_id)
        return "\n".join(
            [
                'resource.type="cloud_run_revision"',
                f'resource.labels.service_name="{service_name}"',
                f'timestamp>="{start_ts}"',
                f'timestamp<="{end_ts}"',
                "(",
                f'  jsonPayload.sessionId="{session_value}"',
                f'  OR textPayload:"{session_value}"',
                ")",
                "(",
                f'  jsonPayload.appEnv="{app_env}"',
                f'  OR labels."run.googleapis.com/service_name"="{service_name}"',
                ")",
            ]
        )


def _to_rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")


def _quote_filter_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
