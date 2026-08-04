from __future__ import annotations

import time
from typing import Any

from app.telemetry.events import log_event as telemetry_log_event


class AimsTurnTelemetry:
    """Small wrapper for AIMS turn telemetry emitted by the coaching handler."""

    def __init__(self, *, logger: Any, model_id: str) -> None:
        self._logger = logger
        self._model_id = model_id

    def classify_begin(self, *, session_id: str, user_info: dict[str, Any] | None, request_id: str) -> None:
        telemetry_log_event(
            self._logger,
            "aims_classify_begin",
            sessionId=session_id,
            userInfo=user_info,
            requestId=request_id,
            modelId=self._model_id,
        )

    def reply_begin(self, *, session_id: str, user_info: dict[str, Any] | None, request_id: str) -> None:
        telemetry_log_event(
            self._logger,
            "aims_reply_begin",
            sessionId=session_id,
            userInfo=user_info,
            requestId=request_id,
            modelId=self._model_id,
        )

    def classify_end(
        self,
        *,
        session_id: str,
        request_id: str,
        started: float,
        model_used: str,
        step: str | None,
        score: int | None,
        semantic_contract: dict[str, bool] | None = None,
    ) -> None:
        semantic_contract = semantic_contract or {}
        telemetry_log_event(
            self._logger,
            "aims_classify_end",
            sessionId=session_id,
            requestId=request_id,
            durationMs=int((time.time() - started) * 1000),
            modelUsed=model_used,
            step=step,
            score=score,
            hasObservations=bool(semantic_contract.get("observations")),
            hasFeedbackItems=bool(semantic_contract.get("feedback_items")),
            hasPersonEvents=bool(semantic_contract.get("person_events")),
            hasResolution=bool(semantic_contract.get("resolution")),
        )

    def reply_end(
        self,
        *,
        session_id: str,
        request_id: str,
        started: float,
        model_used: str,
        text_len: int,
    ) -> None:
        telemetry_log_event(
            self._logger,
            "aims_reply_end",
            sessionId=session_id,
            requestId=request_id,
            durationMs=int((time.time() - started) * 1000),
            modelUsed=model_used,
            textLen=text_len,
        )

    def turn_ok(
        self,
        *,
        latency_ms: int,
        session_id: str,
        user_info: dict[str, Any] | None,
        step: str | None,
        score: int | None,
    ) -> None:
        telemetry_log_event(
            self._logger,
            "aims_turn",
            status="ok",
            latencyMs=latency_ms,
            modelId=self._model_id,
            sessionId=session_id,
            userInfo=user_info,
            step=step,
            score=score,
        )
