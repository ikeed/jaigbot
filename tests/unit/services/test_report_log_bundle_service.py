from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.report_log_bundle_service import ReportLogBundleService


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_collect_and_store_report_logs_uploads_neighbor_artifact():
    storage = MagicMock()
    session = MagicMock()
    session.post.return_value = _FakeResponse({
        "entries": [{"jsonPayload": {"event": "request_start", "sessionId": "sid"}}]
    })
    settings = SimpleNamespace(
        PROJECT_ID="project-1",
        APP_ENV="staging",
        service_name="aimsbot-staging",
    )
    service = ReportLogBundleService(
        storage_service=storage,
        settings_obj=settings,
        auth_default=lambda scopes: ("creds", "project-1"),
        session_cls=lambda creds: session,
    )

    result = service.collect_and_store_report_logs(
        session_id="sid",
        user_id="user@example.com",
        request_id="req-1",
        reported_at=datetime(2026, 6, 11, 19, 0, tzinfo=UTC),
    )

    assert result is storage.upload_report_artifact.return_value
    storage.upload_report_artifact.assert_called_once()
    kwargs = storage.upload_report_artifact.call_args.kwargs
    assert kwargs["session_id"] == "sid"
    assert kwargs["user_id"] == "user@example.com"
    assert kwargs["artifact_suffix"] == "logs.json"
    assert kwargs["payload"]["metadata"]["requestId"] == "req-1"
    assert kwargs["payload"]["metadata"]["serviceName"] == "aimsbot-staging"
    assert kwargs["payload"]["entries"][0]["jsonPayload"]["sessionId"] == "sid"


def test_collect_and_store_report_logs_skips_without_project_id():
    storage = MagicMock()
    settings = SimpleNamespace(
        PROJECT_ID=None,
        APP_ENV="staging",
        service_name="aimsbot-staging",
    )
    service = ReportLogBundleService(storage_service=storage, settings_obj=settings)

    result = service.collect_and_store_report_logs(
        session_id="sid",
        user_id="user@example.com",
        reported_at=datetime(2026, 6, 11, 19, 0, tzinfo=UTC),
    )

    assert result is False
    storage.upload_report_artifact.assert_not_called()


def test_build_filter_scopes_by_session_service_and_time_window():
    storage = MagicMock()
    settings = SimpleNamespace(
        PROJECT_ID="project-1",
        APP_ENV="staging",
        service_name="aimsbot-staging",
    )
    service = ReportLogBundleService(storage_service=storage, settings_obj=settings)

    filter_expr = service._build_filter(
        session_id="sid-123",
        query_start=datetime(2026, 6, 11, 18, 50, tzinfo=UTC),
        query_end=datetime(2026, 6, 11, 19, 2, tzinfo=UTC),
    )

    assert 'resource.type="cloud_run_revision"' in filter_expr
    assert 'resource.labels.service_name="aimsbot-staging"' in filter_expr
    assert 'jsonPayload.sessionId="sid-123"' in filter_expr
    assert 'jsonPayload.appEnv="staging"' in filter_expr
    assert 'timestamp>="2026-06-11T18:50:00Z"' in filter_expr
    assert 'timestamp<="2026-06-11T19:02:00Z"' in filter_expr
