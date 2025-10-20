from __future__ import annotations

from typing import Dict, List


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

    VALID_STEPS = {"Announce", "Inquire", "Mirror", "Secure", "Mirror+Inquire"}

    @staticmethod
    def gate(
        *,
        cls_payload: Dict,
        clinician_text: str,
        parent_last: str,
        parent_recent_concerns: List[str],
        prior_announced: bool,
    ) -> Dict:
        lt_msg = (clinician_text or "").strip().lower()
        pt_msg = (parent_last or "").strip().lower()
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
                    "Non-vaccine rapport/small talk — AIMS not applied"
                ],
                "tips": [
                    "When you're ready, lead with a brief vaccine-specific Announce."
                ],
            }

        return cls_payload


class AimsPostProcessor:
    """Applies post-hoc corrections and score normalization to classification.

    Exact behavior preserved from main.py.
    """

    @staticmethod
    def correct_inquire_to_secure(cls_payload: Dict, clinician_text: str) -> Dict:
        lt = (clinician_text or "").strip().lower()
        if (cls_payload.get("step") == "Inquire") and ("?" not in lt):
            if any(
                tok in lt
                for tok in [
                    "study",
                    "studies",
                    "evidence",
                    "data",
                    "statistic",
                    "percent",
                    "%",
                    "risk",
                    "safe",
                    "side effect",
                    "protect",
                    "immun",
                    "schedule",
                    "dose",
                    "herd immunity",
                ]
            ):
                cls_payload = dict(cls_payload)
                cls_payload["reasons"] = [
                    "Didactic education detected; overriding Inquire to Secure"
                ] + (cls_payload.get("reasons") or [])
                cls_payload["step"] = "Secure"
        return cls_payload

    @staticmethod
    def normalize_score(cls_payload: Dict) -> Dict:
        if (
            cls_payload.get("step") in {"Announce", "Inquire", "Mirror", "Secure", "Mirror+Inquire"}
            and int(cls_payload.get("score", 0)) < 1
        ):
            cls_payload = dict(cls_payload)
            cls_payload["score"] = 1
        return cls_payload

    @staticmethod
    def post_process(cls_payload: Dict, clinician_text: str) -> Dict:
        cls_payload = AimsPostProcessor.correct_inquire_to_secure(cls_payload, clinician_text)
        cls_payload = AimsPostProcessor.normalize_score(cls_payload)
        return cls_payload


class EndGameDetector:
    """Detects conversation end conditions based on the parent's latest reply.

    End when either:
      - Parent agrees to vaccinate now, or
      - Parent prefers a follow-up appointment and to take literature/home materials
    """

    ACCEPT_NOW_CUES = [
        "let's do it", "let’s do it", "lets do it", "do it today", "do the shots today",
        "go ahead and do", "go ahead today", "go ahead with it today", "we can go ahead", "we can go ahead with it today",
        "okay to vaccinate", "ok to vaccinate", "yes, vaccinate", "yes vaccinate",
        "get the vaccine now", "take the vaccine now", "we can do it today",
        "we'll do it today", "we will do it today", "let's get the shot", "let’s get the shot",
        "ready for the shot", "ready for the vaccine", "let's get it today", "let’s get it today",
        "we're ready", "we are ready", "we're ready today", "we are ready today", "ready to proceed", "let's proceed", "proceed today",
        # Consent-based confirmations
        "i consent", "yes, i consent", "we consent", "i give consent",
        "consent to vaccinate", "consent to the vaccine", "consent to the shot",
        "consent for him to get the vaccine", "consent for her to get the vaccine", "consent for my child to get the vaccine",
        "i consent for him to get the vaccine today", "i consent for her to get the vaccine today", "i consent for my child to get the vaccine today",
        "i agree to vaccinate today", "we agree to vaccinate today", "i agree to the vaccine today",
    ]

    FOLLOWUP_CUES = [
        "follow up", "follow-up", "another appointment", "next visit", "come back",
        "schedule", "set up an appointment", "later appointment", "set up",
        "book an appointment", "make an appointment", "schedule something", "talk again",
    ]

    LITERATURE_CUES = [
        "handout", "handouts", "brochure", "pamphlet", "literature", "written info",
        "information to take home", "take home", "materials", "resource", "printout", "printed info",
        "reading", "read this", "give you some literature", "leaflet", "info sheet",
    ]

    @staticmethod
    def detect(patient_reply: str) -> dict | None:
        lt = (patient_reply or "").strip().lower()
        if not lt:
            return None

        # Helper: split into simple sentences by ., !, ? while keeping end char
        import re
        # Normalize whitespace
        lt_norm = re.sub(r"\s+", " ", lt)
        # Split into sentences; keep punctuation to check questions
        parts = re.split(r"(?<=[\.\!\?])\s+", lt_norm) if lt_norm else []
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
            for sent in parts:
                if sentence_accepts(sent):
                    return {"reason": "accepted_now"}
        except Exception:
            # Fallback to original behavior if something goes wrong
            if any(cue in lt for cue in EndGameDetector.ACCEPT_NOW_CUES):
                return {"reason": "accepted_now"}

        # Follow-up AND literature
        if any(c in lt for c in EndGameDetector.FOLLOWUP_CUES) and any(c in lt for c in EndGameDetector.LITERATURE_CUES):
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
        # Drop obvious braces or brackets and code fences
        if s in ("{", "}", "[", "]", "```", "```json", "```md"):
            continue
        if s.startswith("```") or s.endswith("```"):
            continue
        # Drop common JSON key/value looking lines
        if re.match(r'^\s*[\"\']?[A-Za-z0-9_][A-Za-z0-9 _\-]*[\"\']?\s*:', s):
            continue
        if '":' in s or "':" in s:
            continue
        if s.lower().startswith("patient_reply"):
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



def build_endgame_bullets_fallback(session_obj: Dict | None) -> List[str]:
    """Deterministic, plain-text bullet guidance when LLM narrative is unavailable.

    Generates up to 5 actionable bullets using per-step counts and running averages.
    Keeps language empathetic and provides concrete example phrasing.
    """
    bullets: List[str] = []
    if not isinstance(session_obj, dict):
        # Generic advice when no metrics available
        return [
            "Keep Announce brief and clear, then ask an open question to invite concerns.",
            "Inquire: use open-ended prompts (e.g., ‘What are your thoughts about today’s vaccine?’).",
            "Mirror: reflect their words before educating (e.g., ‘It feels like a lot at once — did I get that right?’).",
            "Secure: offer one data-backed point tailored to the specific concern (avoid firehosing).",
        ][:5]

    counts = (session_obj.get("perStepCounts") or {})
    ra = (session_obj.get("runningAverage") or {})

    def avg(step: str) -> float:
        try:
            v = ra.get(step)
            return float(v) if isinstance(v, (int, float)) else float("nan")
        except Exception:
            return float("nan")

    def need_focus(step: str, min_count: int = 1, thresh: float = 2.5) -> bool:
        c = int(counts.get(step, 0) or 0)
        a = avg(step)
        low_avg = (a == a) and (a < thresh)  # a==a filters NaN
        return c < min_count or low_avg

    # 1) Announce
    if need_focus("Announce", min_count=1, thresh=2.5):
        a = ra.get("Announce")
        bullets.append(
            "Announce: lead with a short, non-pushy plan and invite input (e.g., ‘It’s MMR today — how does that sound?’)."
        )

    # 2) Inquire
    if need_focus("Inquire", min_count=2, thresh=2.7):
        bullets.append(
            "Inquire: ask 1–2 open questions to surface concerns (e.g., ‘What’s top of mind about MMR?’ or ‘What have you heard?’)."
        )
    else:
        bullets.append(
            "Nice inquiry pacing — keep questions open and single-barreled, then pause for the parent’s full answer."
        )

    # 3) Mirror
    if need_focus("Mirror", min_count=2, thresh=2.7):
        bullets.append(
            "Mirror: reflect feelings/words before educating (e.g., ‘You’re worried about fever after shots — did I get that right?’)."
        )
    else:
        bullets.append(
            "Your reflections help the parent feel heard — keep mirroring the specific worry before offering facts."
        )

    # 4) Secure
    if need_focus("Secure", min_count=1, thresh=2.6):
        bullets.append(
            "Secure: share one tailored fact, link it to their concern, and check understanding (e.g., ‘A brief fever is common — how does that land?’)."
        )
    else:
        bullets.append(
            "Education was on-point — continue tailoring 1–2 facts to the stated concern and avoid information overload."
        )

    # 5) Close
    bullets.append(
        "Close the loop: confirm plan next steps and appreciation (e.g., ‘Thanks for talking it through — we’ll proceed as discussed.’)."
    )

    # Cap to 5-6 items
    return bullets[:6]
