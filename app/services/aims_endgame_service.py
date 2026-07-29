from __future__ import annotations

import re
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

    def __init__(
        self,
        *,
        logger: Any,
        classifier_service_getter: Callable[[], Any],
        summary_bullets_builder: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        self._logger = logger
        self._classifier_service_getter = classifier_service_getter
        self._summary_bullets_builder = summary_bullets_builder

    @staticmethod
    def _could_be_literature_followup_closure(reply_text: str) -> bool:
        text = (reply_text or "").lower()
        if not text:
            return False
        has_followup = any(cue in text for cue in EndGameDetector.FOLLOWUP_CUES)
        has_literature = EndGameDetector.has_literature_cue(text)
        has_negative = any(cue in text for cue in EndGameDetector.PLAN_NEGATIVE_CUES)
        has_active_concern = any(cue in text for cue in EndGameDetector.PLAN_ACTIVE_CONCERN_CUES)
        return has_followup and has_literature and not has_negative and not has_active_concern

    @staticmethod
    def _recent_exchange_text(history: list[dict[str, Any]]) -> str:
        text = " ".join(
            item.get("content", "")
            for item in history[-10:]
            if item.get("role") in (ROLE_USER, ROLE_ASSISTANT)
            and (item.get("content") or "").strip()
        )
        return text[-1500:]

    @staticmethod
    def _latest_closure_exchange_text(history: list[dict[str, Any]]) -> str:
        """Return the latest clinician/person exchange for closure validation."""
        exchange = [
            item.get("content", "")
            for item in history
            if item.get("role") in (ROLE_USER, ROLE_ASSISTANT)
            and (item.get("content") or "").strip()
        ][-2:]
        return " ".join(exchange)[-1500:]

    async def check(
        self,
        mem: dict[str, Any] | None,
        _reply_payload: dict[str, Any],
        session_obj: dict[str, Any] | None,
        session_id: str,
    ) -> dict[str, Any] | None:
        """Check for end-game scenarios using LLM-centric detection with heuristic fallback."""
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
            first_inquire_done = bool(aims_state.get("first_inquire_done", False))
            has_unmirrored = any(not concern.get("is_mirrored") for concern in concerns)
            literature_followup_closure = (
                heuristic is not None
                and heuristic.get("reason") == "followup_literature"
            )
            possible_literature_followup_closure = self._could_be_literature_followup_closure(
                combined_reply_text
            )
            if (
                concerns
                and has_unmirrored
                and not literature_followup_closure
                and not possible_literature_followup_closure
            ):
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
                has_unsecured = any(not concern.get("is_secured") for concern in concerns)
                if concerns and has_unsecured:
                    is_endgame = False

            if is_endgame and outcome == "accepted_literature":
                combined_lower = combined_reply_text.lower()
                if any(cue in combined_lower for cue in EndGameDetector.PLAN_NEGATIVE_CUES):
                    is_endgame = False
                elif not first_inquire_done or not concerns:
                    is_endgame = False
                elif not (
                    literature_followup_closure
                    or self._could_be_literature_followup_closure(
                        self._latest_closure_exchange_text(history)
                    )
                ):
                    is_endgame = False

            if outcome == "deferred":
                is_endgame = False

            self._log_endgame_end(session_id, started, is_endgame, outcome)

            if not is_endgame:
                return None

            title = endgame_title(session_obj, outcome=outcome)
            lines = [f"Outcome: {summary}"] if summary else []
            llm_commentary: list[str] = []

            try:
                if self._summary_bullets_builder is not None:
                    summary_bullets = await self._summary_bullets_builder(mem)
                    llm_commentary = self._select_summary_commentary(summary_bullets)
            except Exception as e:
                self._logger.debug("Summary analysis failed for endgame coach post: %s", e)

            try:
                fallback_bullets = build_endgame_bullets_fallback(session_obj)
                if fallback_bullets:
                    lines.extend(fallback_bullets)
            except Exception as e:
                self._logger.debug("Deterministic evaluation failed: %s", e)

            if llm_commentary:
                lines.extend(llm_commentary)

            return {"title": title, "lines": lines}

        except Exception as e:
            self._logger.exception("LLM endgame detection failed: %s", e)
            return None

    @staticmethod
    def _select_summary_commentary(summary_bullets: list[str] | None) -> list[str]:
        if not summary_bullets:
            return []

        structural_prefixes = (
            "overall aims score:",
            "announce ",
            "announce:",
            "inquire ",
            "inquire:",
            "mirror ",
            "mirror:",
            "secure ",
            "secure:",
            "outcome:",
        )
        filtered: list[str] = []
        seen: set[str] = set()

        for raw in summary_bullets:
            text = (raw or "").strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered.startswith(structural_prefixes):
                continue
            if re.search(r"\b(announce|inquire|mirror|secure)\b\s+\d+%", lowered):
                continue
            if text in seen:
                continue
            seen.add(text)
            filtered.append(text)

        if len(filtered) < 2:
            return []
        return filtered[:2]

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
