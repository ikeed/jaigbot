from __future__ import annotations

import logging
import re
from typing import Dict, List

from app.message_catalog import message, message_list, message_map

logger = logging.getLogger(__name__)


def _persona_label(session_obj: Dict | None) -> str:
    name = str((session_obj or {}).get("personaName") or "").strip()
    if name:
        return message("endgame.labels.persona_possessive", name=name)
    return message("endgame.labels.persona_possessive_default")


def _patient_label(session_obj: Dict | None) -> str:
    patient_name = str((session_obj or {}).get("patientName") or "").strip()
    if patient_name:
        return message("endgame.labels.patient_possessive", name=patient_name)
    return message("endgame.labels.patient_possessive_default")


_CORE_AIMS_STEPS = ("Announce", "Inquire", "Mirror", "Secure")


def _overall_score_pct(running_average: Dict) -> int | None:
    """Mean of all four core AIMS steps, scaled to 0-100%.

    A step with no recorded turns (e.g. Mirror was never attempted) scores 0,
    not "excluded from the average" - skipping a core step entirely must cost
    at least as much as doing it badly, or the Overall score rewards avoiding
    the harder steps. Returns None only when nothing at all was recorded yet.
    """
    if not any(isinstance(running_average.get(s), (int, float)) for s in _CORE_AIMS_STEPS):
        return None
    core_avgs = [
        float(running_average[s]) if isinstance(running_average.get(s), (int, float)) else 0.0
        for s in _CORE_AIMS_STEPS
    ]
    return int(round((sum(core_avgs) / (len(core_avgs) * 3.0)) * 100))


class VaccineRelevanceGate:
    """Applies vaccine-relevance gating to a classification payload.

    Mirrors the logic in main.py exactly to avoid behavior changes.
    """

    VAX_CUES = message_list("lexicon.coach_post.vaccine_cues")

    VALID_STEPS = {"Announce", "Inquire", "Mirror", "Secure", "Announce+Inquire", "Mirror+Inquire", "Mirror+Secure", "Secure+Inquire", "Mirror+Secure+Inquire"}

    @staticmethod
    def gate(
        *,
        cls_payload: Dict,
        clinician_text: str,
        person_last: str,
        parent_recent_concerns: List[str],
        prior_announced: bool,
        semantic_is_vaccine_relevant: bool | None = None,
        allow_keyword_fallback: bool = False,
    ) -> Dict:
        lt_msg = (clinician_text or "").strip().lower()
        pt_msg = (person_last or "").strip().lower()
        ctx_blob = ("\n".join(parent_recent_concerns) if parent_recent_concerns else "").lower()

        if semantic_is_vaccine_relevant is None and allow_keyword_fallback:
            is_vax_related = (
                any(cue in lt_msg for cue in VaccineRelevanceGate.VAX_CUES)
                or any(cue in pt_msg for cue in VaccineRelevanceGate.VAX_CUES)
                or any(cue in ctx_blob for cue in VaccineRelevanceGate.VAX_CUES)
                or bool(prior_announced)
            )
        elif semantic_is_vaccine_relevant is None:
            is_vax_related = bool(prior_announced)
        else:
            is_vax_related = bool(semantic_is_vaccine_relevant) or bool(prior_announced)

        if not is_vax_related and (cls_payload.get("step") in VaccineRelevanceGate.VALID_STEPS):
            return {
                "step": None,
                "score": 0,
                "reasons": [message("aims.vaccine_gate_reason")],
                "tips": [message("aims.vaccine_gate_tip")],
            }

        return cls_payload


class AimsPostProcessor:
    """Applies post-hoc corrections and score normalization to classification.

    Exact behavior preserved from main.py.
    """

    @staticmethod
    def normalize_score(cls_payload: Dict) -> Dict:
        if (
            cls_payload.get("step") in {"Announce", "Inquire", "Mirror", "Secure", "Announce+Inquire", "Mirror+Inquire", "Mirror+Secure", "Secure+Inquire", "Mirror+Secure+Inquire"}
            and int(cls_payload.get("score", 0)) < 1
        ):
            cls_payload = dict(cls_payload)
            cls_payload["score"] = 1
        return cls_payload

    @staticmethod
    def post_process(
        cls_payload: Dict,
        clinician_text: str,
        *,
        allow_text_softening: bool = False,
    ) -> Dict:
        cls_payload = AimsPostProcessor.normalize_score(cls_payload)
        if cls_payload.get("feedback_items") or not allow_text_softening:
            return cls_payload
        # Soften overly harsh feedback when autonomy-respecting language is present
        try:
            lt = (clinician_text or "").lower()
            autonomy_cues = message_list("lexicon.coach_post.autonomy_softening_cues")
            if any(c in lt for c in autonomy_cues):
                reasons = list(cls_payload.get("reasons") or [])
                # Remove judgmental phrasing markers if present
                markers = message_list("lexicon.coach_post.judgmental_reason_markers")
                filtered = [
                    r
                    for r in reasons
                    if not any(marker in r.lower() for marker in markers)
                ]
                if not filtered and reasons:
                    # Replace with a neutral nudge if we removed everything
                    filtered = [message("state_feedback.neutral_framing_tip")]
                cls_payload = dict(cls_payload)
                cls_payload["reasons"] = filtered
        except Exception as e:
            logger.debug(f"AimsPostProcessor.post_process failed (non-fatal): {e}")
            pass
        return cls_payload


class EndGameDetector:
    """Detects conversation end conditions based on the person's latest reply.

    End when either:
      - Person agrees to vaccinate now, or
      - Person prefers a follow-up appointment and to take literature/home materials
    """

    ACCEPT_NOW_CUES = message_list("lexicon.coach_post.endgame.accept_now_cues")
    FOLLOWUP_CUES = message_list("lexicon.coach_post.endgame.followup_cues")
    LITERATURE_CUES = message_list("lexicon.coach_post.endgame.literature_cues")
    MATERIAL_REVIEW_RES = [
        re.compile(pattern)
        for pattern in message_list("lexicon.coach_post.endgame.material_review_patterns")
    ]
    PLAN_ACCEPTANCE_CUES = message_list("lexicon.coach_post.endgame.plan_acceptance_cues")
    PLAN_NEGATIVE_CUES = message_list("lexicon.coach_post.endgame.plan_negative_cues")
    PLAN_ACTIVE_CONCERN_CUES = message_list("lexicon.coach_post.endgame.plan_active_concern_cues")

    @classmethod
    def has_literature_cue(cls, text: str) -> bool:
        lt = (text or "").lower()
        if any(cue in lt for cue in cls.LITERATURE_CUES):
            return True
        return any(pattern.search(lt) for pattern in cls.MATERIAL_REVIEW_RES)

    @staticmethod
    def detect(patient_reply: str) -> dict | None:
        lt = (patient_reply or "").strip().lower()
        if not lt:
            return None

        # Helper: split into simple sentences by ., !, ? while keeping end char
        # Normalize whitespace
        lt_norm = re.sub(r"\s+", " ", lt)
        # Split into sentences; keep punctuation to check questions
        parts = re.split(r"(?<=[.!?])\s+", lt_norm) if lt_norm else []
        if not parts:
            parts = [lt_norm]

        # Conditional/open-question guard phrases that should suppress acceptance
        conditional_starts = message_list("lexicon.coach_post.endgame.conditional_starts")
        strong_confirms = message_list("lexicon.coach_post.endgame.strong_confirms")

        def sentence_accepts(sent: str) -> bool:
            s = (sent or "").strip()
            if not s:
                return False
            # Guard: ignore sentences that begin with conditionals
            s_nolead = s.lstrip(" \t\n\r-•")
            for pref in conditional_starts:
                if s_nolead.startswith(pref):
                    # Allow only if explicit strong confirmation also present
                    if any(tok in s_nolead for tok in strong_confirms):
                        break
                    return False
            # Guard: if it's a question, require a strong confirmation token
            if s.endswith("?") and not any(tok in s for tok in strong_confirms):
                return False
            # Core cue match
            return any(cue in s for cue in EndGameDetector.ACCEPT_NOW_CUES)

        # Accept now — check per sentence with guards to reduce false positives
        try:
            for sentence in parts:
                if sentence_accepts(sentence):
                    return {"reason": "accepted_now"}
        except Exception as e:
            logger.debug(f"EndGameDetector.detect failed during sentence processing: {e}")
            # Fallback to original behavior if something goes wrong
            if any(cue in lt for cue in EndGameDetector.ACCEPT_NOW_CUES):
                return {"reason": "accepted_now"}

        # Follow-up AND literature require explicit positive acceptance and no negation.
        has_followup = any(c in lt for c in EndGameDetector.FOLLOWUP_CUES)
        has_literature = EndGameDetector.has_literature_cue(lt)
        has_positive_acceptance = any(c in lt for c in EndGameDetector.PLAN_ACCEPTANCE_CUES)
        has_negative_acceptance = any(c in lt for c in EndGameDetector.PLAN_NEGATIVE_CUES)
        has_active_concern = any(c in lt for c in EndGameDetector.PLAN_ACTIVE_CONCERN_CUES)

        if (
            has_followup
            and has_literature
            and has_positive_acceptance
            and not has_negative_acceptance
            and not has_active_concern
        ):
            return {"reason": "followup_literature"}

        return None



def sanitize_endgame_bullets(lines: List[str]) -> List[str]:
    """Clean LLM narrative lines for coach post rendering.

    - Removes JSON/code-like artifacts (braces, key: value, code fences)
    - Strips leading bullet markers and whitespace
    - Deduplicates and caps at 8 bullets to avoid UI overflow
    """
    import re

    out: List[str] = []
    seen: set[str] = set()

    for raw in lines or []:
        s = (raw or "").strip()
        if not s:
            continue
        # Strip surrounding quotes if the whole line is quoted
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()
            if not s:
                continue
        sl = s.lower()
        # Drop obvious braces or brackets and code fences
        if s in ("{", "}", "[", "]", "```", "```json", "```md"):
            continue
        if s.startswith("```") or s.endswith("```"):
            continue
        # Drop common JSON key/value looking lines (require quoted keys to avoid
        # false-positives on legitimate bullets like "Example: ...")
        if re.match(r'^\s*["\']+[A-Za-z0-9_][A-Za-z0-9 _\-]*["\']+\s*:', s):
            continue
        if '":' in s or "':" in s:
            continue
        # Drop stray JSON fragments like patient{ or "patient{
        if sl.startswith("patient{") or sl.startswith('"patient{'):
            continue
        if sl.startswith("patient_reply"):
            continue
        # Drop any line that is just an opening/closing brace with optional quote
        if s.strip().strip('"\'') in ("{", "}"):
            continue
        # Remove leading bullet markers
        s = s.lstrip("-•\t ")
        s = s.strip()
        if not s or s in ("{", "}"):
            continue
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= 8:
            break

    return out



def endgame_title(session_obj: Dict | None, outcome: str = "") -> str:
    """Return a score-calibrated celebratory title for the end-of-session card.

    Overall score (mean of core AIMS step averages, scaled to 0-100%):
      >= 85%  -> "🎉 Excellent job!"
      >= 70%  -> "🎉 Great job!"
      >= 55%  -> "🎉 Good job!"
      <  55%  -> "🎉 Nice job!"
    Falls back to 'Great job!' when no score data is available.
    """
    if outcome == "deferred":
        return message("endgame.titles.deferred")
    try:
        ra = (session_obj or {}).get("runningAverage") or {}
        overall = _overall_score_pct(ra)
        if overall is None:
            return message("endgame.titles.great")
        if overall >= 85:
            return message("endgame.titles.excellent")
        if overall >= 70:
            return message("endgame.titles.great")
        if overall >= 55:
            return message("endgame.titles.good")
        return message("endgame.titles.nice")
    except Exception as e:
        logger.debug(f"Error determining endgame title: {e}")
        return message("endgame.titles.great")


def build_endgame_bullets_fallback(session_obj: Dict | None) -> List[str]:
    """Contextual, score-aware feedback bullets for the end-of-session Great Job card.

    Shows overall AIMS score percentage followed by per-step feedback calibrated
    to the clinician's actual performance in this session.
    """
    # Score range helpers
    _HIGH = 2.4    # >= 80%
    _MID  = 1.8    # >= 60%
    persona_label = _persona_label(session_obj)
    patient_label = _patient_label(session_obj)

    catalog_messages = message_map("endgame.fallback_bullets")
    step_messages: Dict[str, Dict[str, str]] = {
        step: dict(value)
        for step, value in catalog_messages.items()
        if isinstance(value, dict)
    }

    if not isinstance(session_obj, dict):
        return [
            item.format(persona_label=persona_label, patient_label=patient_label)
            for item in message_list("endgame.fallback_bullets.default")
        ]

    counts = (session_obj.get("perStepCounts") or {})
    ra     = (session_obj.get("runningAverage") or {})

    def _avg(step: str) -> float:
        try:
            v = ra.get(step)
            return float(v) if isinstance(v, (int, float)) else float("nan")
        except Exception as e:
            logger.debug(f"Error calculating average score for {step}: {e}")
            return float("nan")

    def _pct(a: float) -> int:
        """Convert a 1-3 average to a 0-100 integer percentage."""
        return int(round((a / 3.0) * 100))

    bullets: List[str] = []

    # 1. Overall score across all four core AIMS steps (a step never attempted
    # scores 0, it isn't excluded - see _overall_score_pct).
    overall_pct = _overall_score_pct(ra)
    if overall_pct is not None:
        bullets.append(message("endgame.overall_score", pct=overall_pct))

    # 2. Per-step contextual feedback
    secure_before_mirror_count = int(session_obj.get("secureBeforeMirrorCount", 0) or 0)
    for step_name in ("Announce", "Inquire", "Mirror", "Secure"):
        c = int(counts.get(step_name, 0) or 0)
        a = _avg(step_name)
        msgs = step_messages.get(step_name, {})

        def _step_message(tier: str) -> str:
            template = str(msgs.get(tier) or "")
            return template.format(
                persona_label=persona_label,
                patient_label=patient_label,
            )

        if step_name == "Secure" and secure_before_mirror_count > 0:
            # Securing without mirroring first is the single most consequential
            # AIMS mistake a clinician can make, so it always leads the Secure
            # summary regardless of the numeric score band.
            topic_hint = str(session_obj.get("secureBeforeMirrorTopicHint") or "")
            if secure_before_mirror_count == 1 and topic_hint:
                unmirrored_text = message(
                    "endgame.fallback_bullets.Secure.unmirrored_warning_single",
                    topic_hint=topic_hint,
                )
            else:
                unmirrored_text = message(
                    "endgame.fallback_bullets.Secure.unmirrored_warning",
                    count=secure_before_mirror_count,
                    times_word="time" if secure_before_mirror_count == 1 else "times",
                    persona_label=persona_label,
                )
            if c == 0 or a != a:
                bullets.append(f"Secure: {unmirrored_text}")
            else:
                bullets.append(f"Secure {_pct(a)}% - {unmirrored_text}")
            continue

        if c == 0 or a != a:  # step not used or no score data
            bullets.append(f"{step_name}: {_step_message('absent')}")
        elif a >= _HIGH:
            bullets.append(f"{step_name} {_pct(a)}% - {_step_message('high')}")
        elif a >= _MID:
            bullets.append(f"{step_name} {_pct(a)}% - {_step_message('mid')}")
        else:
            bullets.append(f"{step_name} {_pct(a)}% - {_step_message('low')}")

    return bullets[:6]
