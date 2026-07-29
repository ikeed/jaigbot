from __future__ import annotations

import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)


def _persona_label(session_obj: Dict | None) -> str:
    name = str((session_obj or {}).get("personaName") or "").strip()
    return f"{name}'s" if name else "the parent's"


def _patient_label(session_obj: Dict | None) -> str:
    patient_name = str((session_obj or {}).get("patientName") or "").strip()
    return f"{patient_name}'s" if patient_name else "the patient's"


class VaccineRelevanceGate:
    """Applies vaccine-relevance gating to a classification payload.

    Mirrors the logic in main.py exactly to avoid behavior changes.
    """

    VAX_CUES = [
        "vaccine",
        "vaccin",
        "shot",
        "jab",
        "jabs",
        "mmr",
        "measles",
        "booster",
        "immuniz",
        "side effect",
        "adverse event",
        "vaers",
        "thimerosal",
        "immunity",
        "immune",
        "schedule",
        "dose",
        "hib",
        "pcv",
        "hepb",
        "mmrv",
        "rotavirus",
        "pertussis",
        "varicella",
        "dtap",
        "polio",
        "option",
        "options",
        "decision",
    ]

    VALID_STEPS = {"Announce", "Inquire", "Mirror", "Secure", "Announce+Inquire", "Mirror+Inquire", "Mirror+Secure", "Secure+Inquire", "Mirror+Secure+Inquire"}

    @staticmethod
    def gate(
        *,
        cls_payload: Dict,
        clinician_text: str,
        person_last: str,
        parent_recent_concerns: List[str],
        prior_announced: bool,
    ) -> Dict:
        lt_msg = (clinician_text or "").strip().lower()
        pt_msg = (person_last or "").strip().lower()
        ctx_blob = ("\n".join(parent_recent_concerns) if parent_recent_concerns else "").lower()

        is_vax_related = (
            any(cue in lt_msg for cue in VaccineRelevanceGate.VAX_CUES)
            or any(cue in pt_msg for cue in VaccineRelevanceGate.VAX_CUES)
            or any(cue in ctx_blob for cue in VaccineRelevanceGate.VAX_CUES)
            or bool(prior_announced)
        )

        if not is_vax_related and (cls_payload.get("step") in VaccineRelevanceGate.VALID_STEPS):
            return {
                "step": None,
                "score": 0,
                "reasons": [
                    "Rapport/symptom gathering in progress. Waiting for vaccine Announce."
                ],
                "tips": [
                    "Vaccine coaching will begin after vaccination is introduced."
                ],
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
    def post_process(cls_payload: Dict, clinician_text: str) -> Dict:
        cls_payload = AimsPostProcessor.normalize_score(cls_payload)
        # Soften overly harsh feedback when autonomy-respecting language is present
        try:
            lt = (clinician_text or "").lower()
            autonomy_cues = (
                "no pressure",
                "it’s your choice",
                "it's your choice",
                "up to you",
                "your decision",
                "happy to answer",
                "any questions",
                "open to talking",
            )
            if any(c in lt for c in autonomy_cues):
                reasons = list(cls_payload.get("reasons") or [])
                # Remove judgmental phrasing markers if present
                filtered = [r for r in reasons if ("judgment" not in r.lower() and "leading" not in r.lower())]
                if not filtered and reasons:
                    # Replace with a neutral nudge if we removed everything
                    filtered = ["Keep framing neutral and open; invite questions."]
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

    ACCEPT_NOW_CUES = [
        "let's do it", "let’s do it", "lets do it", "do it today", "do the shots today",
        "go ahead and do", "go ahead today", "go ahead with it today", "we can go ahead", "we can go ahead with it today",
        "okay to vaccinate", "ok to vaccinate", "yes, vaccinate", "yes vaccinate",
        "get the vaccine now", "take the vaccine now", "we can do it today",
        "we'll do it today", "we will do it today", "let's get the shot", "let’s get the shot",
        "ready for the shot", "ready for the vaccine", "let's get it today", "let’s get it today",
        "we're ready", "we are ready", "we're ready today", "we are ready today", "ready to proceed", "let's proceed", "proceed today",
        "let's go ahead", "let’s go ahead",
        # Consent-based confirmations
        "i consent", "yes, i consent", "we consent", "i give consent",
        "consent to vaccinate", "consent to the vaccine", "consent to the shot",
        "consent for him to get the vaccine", "consent for her to get the vaccine", "consent for my child to get the vaccine",
        "i consent for him to get the vaccine today", "i consent for her to get the vaccine today", "i consent for my child to get the vaccine today",
        "i agree to vaccinate today", "we agree to vaccinate today", "i agree to the vaccine today",
        # Naturalistic acceptance phrasing
        "comfortable proceeding", "i'm comfortable proceeding", "i am comfortable proceeding",
        "comfortable with proceeding", "comfortable going ahead", "comfortable with the",
        "i feel good about proceeding", "feel confident in proceeding",
        "i'm on board", "i am on board", "on board with",
        "comfortable moving forward", "comfortable with moving forward", "happy to move forward",
        "move forward with it", "move forward today", "happy to proceed",
        "ready to go ahead", "i'm ready to go ahead", "i am ready to go ahead",
        "ready to go ahead with it", "i'm ready to go ahead with it", "i am ready to go ahead with it",
    ]

    FOLLOWUP_CUES = [
        "follow up", "follow-up", "another appointment", "next visit", "come back",
        "schedule", "set up an appointment", "later appointment", "book an appointment",
        "make an appointment", "schedule something", "make another", "appointment",
        "talk again", "talk about it again", "talk it over again", "talk more",
        "revisit this", "revisit it", "review this in", "review it in",
    ]

    LITERATURE_CUES = [
        "handout", "handouts", "brochure", "pamphlet", "literature", "written info",
        "information to take home", "take home", "materials", "resource", "printout", "printed info",
        "read this", "give you some literature", "leaflet", "info sheet",
        "look over", "at home", "read over", "information",
    ]

    MATERIAL_REVIEW_RE = re.compile(
        r"\b(?:review|read|look over|look through|go over|take|bring|send|give|print)\b"
        r"[\w\s'-]{0,80}\b(?:papers|paperwork|printed schedule|printed materials)\b"
        r"|"
        r"\b(?:papers|paperwork|printed schedule|printed materials)\b"
        r"[\w\s'-]{0,80}\b(?:review|read|look over|look through|go over|take home|bring home)\b"
    )

    PLAN_ACCEPTANCE_CUES = [
        "sounds good", "sounds like a plan", "that would help", "would be helpful",
        "would be very helpful", "that would be helpful", "excellent approach",
        "reasonable plan", "helpful for me", "i'd like that", "i would like that",
        "yes,", "yes ", "helpful", "sounds reasonable", "works for me",
        "i'll take", "i will take", "talk about it at the next appointment",
        "talk about it at the next visit", "we can talk about it",
        "decide at the next appointment", "decide at the next visit",
        "we can decide",
    ]

    PLAN_NEGATIVE_CUES = [
        "don't want", "do not want", "not going to read", "would not help",
        "wouldn't help", "not helpful", "no point", "don't think", "do not think",
        "not interested", "rather not", "won't read", "will not read",
    ]

    PLAN_ACTIVE_CONCERN_CUES = [
        "still worried", "still worry", "still concerned", "still nervous",
        "still scared", "not convinced", "not sure", "do not trust",
        "don't trust", "safety risk", "unsafe", "still a risk",
    ]

    @classmethod
    def has_literature_cue(cls, text: str) -> bool:
        lt = (text or "").lower()
        if any(cue in lt for cue in cls.LITERATURE_CUES):
            return True
        return bool(cls.MATERIAL_REVIEW_RE.search(lt))

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
        conditional_starts = (
            "if we ", "if i ", "if we do ", "if i do ", "if we were to ", "if i were to ",
            "if we decide ", "if i decide ", "if we choose ", "if i choose ", "if we go ahead ", "if i go ahead ",
        )
        strong_confirms = (
            "i consent", "we consent", "yes, i consent", "i agree", "we agree",
            "we're ready", "we are ready", "ready to proceed", "let's proceed", "we can do it today",
        )

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
        return "Session Complete"
    try:
        ra = (session_obj or {}).get("runningAverage") or {}
        core_avgs = [
            float(ra[s]) for s in ("Announce", "Inquire", "Mirror", "Secure")
            if isinstance(ra.get(s), (int, float))
        ]
        if not core_avgs:
            return "🎉 Great job!"
        overall = sum(core_avgs) / (len(core_avgs) * 3.0) * 100
        if overall >= 85:
            return "🏆 Excellent job!"
        if overall >= 70:
            return "🎉 Great job!"
        if overall >= 55:
            return "👏 Good job!"
        return "💪 Nice job!"
    except Exception as e:
        logger.debug(f"Error determining endgame title: {e}")
        return "🎉 Great job!"


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

    # Per-step messages keyed by performance tier
    _MSGS: Dict[str, Dict[str, str]] = {
        "Announce": {
            "high": "clear, non-pressuring recommendation — well done.",
            "mid":  "the recommendation was present; try making it more concise and following immediately with an open question.",
            "low":  f"lead with a brief presumptive recommendation, then invite input (e.g., \"{patient_label} due for MMR today — what are your thoughts?\").",
            "absent": "introduce vaccines with a clear, non-pushy recommendation before asking for concerns.",
        },
        "Inquire": {
            "high": f"strong open questions that surfaced {persona_label} real concerns.",
            "mid":  "good inquiry; when closing the loop, explicitly invite any remaining concerns or what is still on their mind.",
            "low":  "use open-ended questions to surface concerns (e.g., \"What's still on your mind about vaccines today?\") before educating.",
            "absent": f"ask at least one open-ended question to discover {persona_label} specific concerns before educating.",
        },
        "Mirror": {
            "high": "excellent reflections — you consistently captured the concern before moving forward.",
            "mid":  "good reflections; make sure to capture the underlying value (not just the stated concern) and check for accuracy.",
            "low":  f"reflect {persona_label} concern before educating (e.g., \"It sounds like you want to be sure this is safe — did I get that right?\").",
            "absent": f"mirror {persona_label} concern back to them before offering any education — it makes them feel heard.",
        },
        "Secure": {
            "high": "education was well-tailored to the stated concerns without overwhelming.",
            "mid":  "solid education; try adding an explicit check-in after key facts (e.g., \"How does that land for you?\") to avoid a lecture feel.",
            "low":  "keep Secure focused: one tailored fact, linked directly to the concern, then check in (e.g., \"Does that help with the ingredient question?\"). Avoid long explanations without pauses.",
            "absent": "provide targeted education addressing the stated concern, then check understanding.",
        },
    }

    if not isinstance(session_obj, dict):
        return [
            "Announce: lead with a short, non-pushy recommendation and invite input.",
            "Inquire: ask open-ended questions to surface the parent's specific concerns.",
            "Mirror: reflect their words and emotions before educating.",
            "Secure: share one tailored fact linked to the concern, then check understanding.",
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

    # 1. Overall score from core AIMS steps that were actually used
    core_avgs = [_avg(s) for s in ("Announce", "Inquire", "Mirror", "Secure")]
    core_avgs = [a for a in core_avgs if a == a]  # drop NaN
    if core_avgs:
        overall_pct = int(round((sum(core_avgs) / (len(core_avgs) * 3.0)) * 100))
        bullets.append(f"Overall AIMS score: {overall_pct}%")

    # 2. Per-step contextual feedback
    for step_name in ("Announce", "Inquire", "Mirror", "Secure"):
        c = int(counts.get(step_name, 0) or 0)
        a = _avg(step_name)
        msgs = _MSGS[step_name]

        if c == 0 or a != a:  # step not used or no score data
            bullets.append(f"{step_name}: {msgs['absent']}")
        elif a >= _HIGH:
            bullets.append(f"{step_name} {_pct(a)}% \u2014 {msgs['high']}")
        elif a >= _MID:
            bullets.append(f"{step_name} {_pct(a)}% \u2014 {msgs['mid']}")
        else:
            bullets.append(f"{step_name} {_pct(a)}% \u2014 {msgs['low']}")

    return bullets[:6]
