from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.chat_roles import ROLE_ASSISTANT, ROLE_USER, get_ui_attributes
from app.constants import KEY_AIMS_STATE, PHASE_PRE_ANNOUNCE, SESSION_HISTORY
from app.services.coach_post import (
    EndGameDetector,
    build_endgame_bullets_fallback,
    endgame_title,
)
from app.telemetry.events import log_event as telemetry_log_event


class AimsEndgameService:
    """Detects completed AIMS sessions and builds final coach posts."""

    def __init__(self, *, logger: Any, classifier_service_getter: Callable[[], Any]) -> None:
        self._logger = logger
        self._classifier_service_getter = classifier_service_getter

    async def check(
        self,
        mem: dict[str, Any] | None,
        reply_payload: dict[str, Any],
        session_obj: dict[str, Any] | None,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Check for end-game scenarios using LLM-centric detection with heuristic fallback."""
        del reply_payload
        started = time.time()
        try:
            if mem is None:
                return None

            history = mem.get(SESSION_HISTORY) or []
            aims_state = mem.get(KEY_AIMS_STATE) or {}

            phase = aims_state.get("phase", PHASE_PRE_ANNOUNCE)
            announced = aims_state.get("announced", False)
            if phase == PHASE_PRE_ANNOUNCE:
                return None

            assistant_count = sum(
                1
                for item in history
                if item.get("role") == ROLE_ASSISTANT and (item.get("content") or "").strip()
            )
            if not announced and assistant_count <= 1:
                return None

            combined_reply_text = " ".join(
                item.get("content", "")
                for item in reversed(history[-6:])
                if item.get("role") == ROLE_ASSISTANT and (item.get("content") or "").strip()
            )[:500]
            heuristic = EndGameDetector.detect(combined_reply_text)

            concerns = aims_state.get("parent_concerns") or []
            has_unmirrored = any(not concern.get("is_mirrored") for concern in concerns)
            literature_followup_closure = (
                heuristic is not None
                and heuristic.get("reason") == "followup_literature"
            )
            if concerns and has_unmirrored and not literature_followup_closure:
                return None

            history_text = "\n".join(
                f"{get_ui_attributes(item.get('role'))['author']}: {item.get('content')}"
                for item in history[-10:]
                if item.get("role") in (ROLE_USER, ROLE_ASSISTANT)
            )

            inquired = [concern["topic"] for concern in concerns]
            mirrored = [concern["topic"] for concern in concerns if concern.get("is_mirrored")]
            secured = [concern["topic"] for concern in concerns if concern.get("is_secured")]

            self._log_endgame_begin(session_id, inquired, mirrored, secured)

            result = await self._classifier_service_getter().detect_endgame(
                history_text=history_text,
                announced=announced,
                inquired_concerns=inquired,
                mirrored_concerns=mirrored,
                secured_concerns=secured,
            )

            is_endgame = result.get("is_endgame", False)
            outcome = result.get("resolution_type", "not_resolved")
            summary = result.get("summary", "")

            if not is_endgame and heuristic:
                is_endgame = True
                heuristic_reason = heuristic.get("reason", "")
                outcome = (
                    "accepted_vaccine"
                    if heuristic_reason == "accepted_now"
                    else "accepted_literature"
                )
                summary = ""

            if is_endgame and outcome == "accepted_vaccine":
                heuristic = EndGameDetector.detect(combined_reply_text)
                if not heuristic or heuristic.get("reason") != "accepted_now":
                    is_endgame = False

            if is_endgame and outcome == "accepted_literature":
                combined_lower = combined_reply_text.lower()
                if any(cue in combined_lower for cue in EndGameDetector.PLAN_NEGATIVE_CUES):
                    is_endgame = False

            if outcome == "deferred":
                is_endgame = False

            self._log_endgame_end(session_id, started, is_endgame, outcome)

            if not is_endgame:
                return None

            title = endgame_title(session_obj, outcome=outcome)
            lines = [f"Outcome: {summary}"] if summary else []

            try:
                fallback_bullets = build_endgame_bullets_fallback(session_obj)
                if fallback_bullets:
                    lines.extend(fallback_bullets)
            except Exception as e:
                self._logger.debug("Deterministic evaluation failed: %s", e)

            return {"title": title, "lines": lines}

        except Exception as e:
            self._logger.exception("LLM endgame detection failed: %s", e)
            return None

    def _log_endgame_begin(
        self,
        session_id: str,
        inquired: list[str],
        mirrored: list[str],
        secured: list[str],
    ) -> None:
        try:
            telemetry_log_event(
                self._logger,
                "aims_endgame_begin",
                sessionId=session_id,
                inquiredCount=len(inquired),
                mirroredCount=len(mirrored),
                securedCount=len(secured),
            )
        except Exception as e:
            self._logger.debug("Endgame begin telemetry failed: %s", e)

    def _log_endgame_end(
        self,
        session_id: str,
        started: float,
        is_endgame: bool,
        outcome: str,
    ) -> None:
        try:
            telemetry_log_event(
                self._logger,
                "aims_endgame_end",
                sessionId=session_id,
                durationMs=int((time.time() - started) * 1000),
                isEndgame=is_endgame,
                outcome=outcome,
            )
        except Exception as e:
            self._logger.debug("Endgame end telemetry failed: %s", e)
