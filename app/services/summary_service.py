from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from app.chat_roles import ROLE_ASSISTANT, get_ui_attributes
from app.telemetry.events import log_event as telemetry_log_event

logger = logging.getLogger(__name__)


DEFAULT_STEP_COVERAGE = {"Announce": 0, "Inquire": 0, "Mirror": 0, "Secure": 0}


async def build_summary(
    *,
    session_id: str | None,
    analysis: bool,
    memory_store: Any,
    memory_enabled: bool,
    settings: Any,
    logger: logging.Logger,
    app_state: Any,
    vertex_client_cls: Any,
) -> dict:
    """Return the aggregated AIMS summary for a stored session."""
    base = _base_summary()
    if not session_id or not memory_enabled:
        if analysis:
            base["analysis"] = []
        return base

    mem = memory_store.get(session_id) or {}
    aims = mem.get("aims") or {}
    per_counts = _step_counts(aims)
    running_avg = _running_average(aims)
    overall = (sum(running_avg.values()) / len(running_avg)) if running_avg else 0.0

    base.update({
        "overallScore": overall,
        "stepCoverage": per_counts,
        "runningAverage": running_avg,
        "strengths": [],
        "growthAreas": [],
        "totalTurns": aims.get("totalTurns", 0),
    })

    if not analysis:
        return base

    try:
        base["analysis"] = await _analysis_bullets(
            mem=mem,
            aims=aims,
            per_counts=per_counts,
            settings=settings,
            logger=logger,
            app_state=app_state,
            vertex_client_cls=vertex_client_cls,
        )
    except Exception as exc:
        telemetry_log_event(logger, "summary_analysis_failed", sessionId=session_id, error=str(exc))
        base["analysis"] = []

    return base


def _base_summary() -> dict:
    return {
        "overallScore": 0.0,
        "stepCoverage": dict(DEFAULT_STEP_COVERAGE),
        "strengths": [],
        "growthAreas": [],
    }


def _step_counts(aims: dict) -> dict[str, int]:
    per_counts = dict(DEFAULT_STEP_COVERAGE)
    per_counts.update(aims.get("perStepCounts", {}))
    return per_counts


def _running_average(aims: dict) -> dict[str, float]:
    running_avg: dict[str, float] = {}
    for key, scores in (aims.get("scores", {}) or {}).items():
        if scores:
            try:
                running_avg[key] = sum(scores) / len(scores)
            except Exception as e:
                logger.debug("Failed to calculate running average for %s: %s", key, e)
                pass
    return running_avg


async def _analysis_bullets(
    *,
    mem: dict,
    aims: dict,
    per_counts: dict[str, int],
    settings: Any,
    logger: logging.Logger,
    app_state: Any,
    vertex_client_cls: Any,
) -> list[str]:
    transcript = _build_transcript(mem)
    mapping = _load_mapping(app_state)

    metrics_blob = json.dumps({
        "totalTurns": aims.get("totalTurns", 0),
        "perStepCounts": per_counts,
        "runningAverage": aims.get("runningAverage", {}),
    }, ensure_ascii=False)
    mapping_blob = json.dumps(mapping or {}, ensure_ascii=False)

    from app.prompts.aims import build_summary_analysis_prompt
    prompt = build_summary_analysis_prompt(
        metrics_blob=metrics_blob,
        mapping_blob=mapping_blob,
        transcript=transcript,
    )

    from app.services import vertex_helpers

    narrative = await asyncio.to_thread(
        vertex_helpers.vertex_call_with_fallback_text,
        project=settings.PROJECT_ID,
        region=settings.VERTEX_LOCATION,
        primary_model="gemini-2.5-flash",
        fallbacks=[settings.MODEL_ID] + list(settings.MODEL_FALLBACKS or []),
        temperature=min(settings.TEMPERATURE, 0.2),
        max_tokens=min(settings.MAX_TOKENS, 384),
        prompt=prompt,
        system_instruction=None,
        log_path="summary_analysis",
        logger=logger,
        client_cls=vertex_client_cls,
    )
    bullets_raw = [line for line in (narrative or "").strip().splitlines() if line.strip()]
    try:
        from app.services.coach_post import sanitize_endgame_bullets
        bullets = sanitize_endgame_bullets(bullets_raw)
    except Exception as e:
        logger.debug("Failed to sanitize bullets: %s", e)
        bullets = [line.strip(" -\t") for line in bullets_raw]

    return _enforce_metrics_consistency(bullets, per_counts)


def _build_transcript(mem: dict) -> str:
    try:
        parts = []
        for item in mem.get("history") or []:
            role = item.get("role") or ROLE_ASSISTANT
            author = get_ui_attributes(role)["author"]
            text = (item.get("content") or "").strip()
            if text:
                parts.append(f"{author}: {text}")
        return "\n".join(parts)
    except Exception as e:
        logger.debug("Failed to build transcript: %s", e)
        return ""


def _load_mapping(app_state: Any) -> dict:
    mapping = getattr(app_state, "aims_mapping", None)
    if mapping is not None:
        return mapping
    try:
        from app.aims_engine import load_mapping
        mapping = load_mapping()
        app_state.aims_mapping = mapping
        return mapping
    except Exception as e:
        logger.debug("Failed to load mapping: %s", e)
        return {}


def _enforce_metrics_consistency(bullets_in: list[str], step_counts: dict[str, int]) -> list[str]:
    present = {key for key, value in (step_counts or {}).items() if isinstance(value, int) and value > 0}
    pattern = re.compile(
        r"\b(Announce|Inquire|Mirror|Secure)\b.*\b(skipped|missing|didn't happen|did not happen|not used)\b",
        re.IGNORECASE,
    )
    cleaned: list[str] = []
    for bullet in bullets_in or []:
        match = pattern.search(bullet or "")
        if match and (match.group(1) in present):
            step = match.group(1)
            rewrites = {
                "Announce": "Announce occurred - keep it concise and invite input (e.g., 'It's MMR today - how does that sound?').",
                "Inquire": "Inquire was present - prioritize open-ended questions and pause for the full answer.",
                "Mirror": "Mirror was used - keep reflecting the exact worry before educating.",
                "Secure": "Secure was present - share one tailored fact, link to the concern, and check understanding.",
            }
            cleaned.append(rewrites.get(step, bullet))
        else:
            cleaned.append(bullet)

    out: list[str] = []
    seen = set()
    for item in cleaned:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out
