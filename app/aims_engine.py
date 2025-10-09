"""
Deterministic AIMS engine: loader, classifier, and scorer.

Pure-Python utilities that do not call any LLM. These are used for
classification and per-turn scoring using the docs/aims/aims_mapping.json
as the source of truth.

Functions are intentionally simple and conservative; they implement the
markers and tie-breakers described in the mapping meta section.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

# Regex patterns for small-talk detection of generic well-being questions
_GENERIC_WELLBEING_Q = re.compile(
    r"^(has|is|are|how('?s| is))\s+(he|she|they|your\s+\w+)\s+(been\s+)?"
    r"(sleep|sleeping|napping|eating|pooping|poo|stooling|peeing|pee|diapers?|teething|daycare|preschool|school|weekend|birthday|morning|afternoon|evening)\b.*\?$"
)

# Tokens that indicate clinical assessment/decision content (not small talk)
_CLINICAL_TOKENS = re.compile(
    r"\b(vaccine|shot|mmr|booster|immuniz|due|rash today|fever today|pain today|vomiting|dehydrated|lethargic|wheezing|croup|pneumonia|ER|urgent care)\b"
)


AIMS_STEPS = ("Announce", "Inquire", "Mirror", "Secure")


@dataclass
class ClassificationResult:
    step: str
    reasons: List[str]


@dataclass
class ScoreResult:
    score: int
    reasons: List[str]


def load_mapping(path: Optional[str] = None) -> Dict[str, Any]:
    """Load aims_mapping.json.

    If path is None, attempt to resolve it at docs/aims/aims_mapping.json
    relative to the repository root (in tests, cwd is repo root).
    """
    candidates: List[str] = []
    if path:
        candidates.append(path)
    # relative to project root
    candidates.append(os.path.join("docs", "aims", "aims_mapping.json"))
    # sometimes tests may run from a nested cwd; try up to two levels up
    candidates.append(os.path.join("..", "docs", "aims", "aims_mapping.json"))
    candidates.append(os.path.join("..", "..", "docs", "aims", "aims_mapping.json"))

    last_err: Optional[Exception] = None
    for p in candidates:
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:  # pragma: no cover (only on failure path)
            last_err = e
            continue
    # If all failed, raise the last error or a friendly message
    if last_err:
        raise FileNotFoundError(f"Unable to load aims_mapping.json; tried: {candidates}: {last_err}")
    raise FileNotFoundError(f"Unable to load aims_mapping.json; tried: {candidates}")


def _stem_match(text: str, stems: List[str]) -> bool:
    t = text.strip().lower()
    for s in stems:
        s_norm = s.strip().lower()
        if not s_norm:
            continue
        if s_norm in t:
            return True
    return False


def _starts_with_any(text: str, starters: List[str]) -> bool:
    t = text.strip().lower()
    return any(t.startswith(s.strip().lower()) for s in starters if s.strip())


def _is_small_talk(text: str) -> bool:
    """Detect pleasantries/rapport/openers that are not an AIMS step.

    Heuristics: greetings, compliments, social niceties (no clinical content),
    and generic well-being check-ins. Works for single- or multi-sentence turns
    (e.g., rapport sentence followed by "Has he been sleeping ok?").
    We keep this conservative: only return True when such phrases are present;
    caller should also ensure no AIMS markers matched.
    """
    lt = (text or "").strip().lower()
    if not lt:
        return False
    cues = [
        "hello", "hi ", "hi,", "hey", "good to see", "nice to see", "so good to see",
        "great to see", "welcome", "how are you", "how’s it going", "how's it going",
        "wow", "getting so big", "so big", "big boy", "big girl", "eating all of",
        "vegetable", "thanks for coming", "good to see both of you", "so good to see both",
        # Added rapport/compliment/growth phrases
        "how he's grown", "how she’s grown", "how she's grown", "grown so much", "so grown up",
        "look how big", "so cute", "adorable", "handsome little", "big guy", "big man",
        "buddy", "champ", "big and strong", "looks big", "looks so big", "he looks big", "she looks big"
    ]
    # Basic cue check
    if any(c in lt for c in cues):
        return True
    # Exclamatory rapport without clinical tokens → treat as small talk
    if lt.endswith("!") and not re.search(r"\b(vaccine|shot|mmr|booster|immuniz|due)\b", lt):
        return True
    # Question-form generic well-being rapport (sleep/eat/teething/daycare/etc.)
    # Support multi-sentence: extract the trailing question sentence and test it.
    if "?" in lt and not _CLINICAL_TOKENS.search(lt):
        m = re.search(r"([^.?!]*\?)\s*$", lt)
        if m:
            last_q = m.group(1).strip()
            if _GENERIC_WELLBEING_Q.match(last_q):
                return True
    return False


def classify_step(parent_last: str, clinician_last: str, mapping: Dict[str, Any]) -> ClassificationResult:
    """Classify the clinician's last message into one AIMS step.

    Implements the decision rules and tie-breakers from mapping['meta'].
    """
    meta = (mapping or {}).get("meta", {})
    markers = meta.get("per_step_classification_markers", {})
    reasons: List[str] = []
    text = (clinician_last or "").strip()
    pt = (parent_last or "").strip().lower()
    lt = text.lower()

    # Early rapport guard for question-form small talk (so it doesn't get mislabeled as Inquire)
    if lt.endswith("?") and _is_small_talk(lt):
        return ClassificationResult(step="", reasons=["Rapport/pleasantries detected — no AIMS step attempted (allowed)."])

    # Heuristic checks per step
    mirror_match = _starts_with_any(lt, [
        "it sounds like", "you're worried", "you are worried", "i'm hearing", "you feel", "you want",
        "i get you're", "i get that you're", "i hear you're", "i hear that you're", "i hear you", "i hear that"
    ]) or _stem_match(lt, (markers.get("Mirror", {}).get("linguistic", [])))

    inquire_match = lt.endswith("?") or _starts_with_any(lt, ["what ", "how "]) or _stem_match(
        lt, (markers.get("Inquire", {}).get("linguistic", []))
    )

    # Strengthened Secure detection: autonomy + (option or safety) OR option + safety
    autonomy_cues = [
        "it's your decision", "it's your call", "up to you", "your choice", "i'm here to support"
    ]
    option_re = re.compile(
        r"\b("
        r"we can (do it|give it|get it|do the shot|schedule|wait|hold off|review|go over|share|check in)"
        r"|do it (today|now)"
        r"|today or (later|next week)"
        r"|now or later"
        r"|options include"
        r"|prefer"
        r"|handout"
        r"|follow-?up"
        r"|check in"
        r"|schedule"
        r")\b"
    )
    safety_re = re.compile(r"\b(what to expect|watch for|call if|reach (out|me)|how to reach|fever|redness|soreness|tylenol|acetaminophen|ibuprofen)\b")

    has_autonomy = _stem_match(lt, autonomy_cues)
    # Guard against bare "we can" without a concrete option/action
    has_option = bool(option_re.search(lt))
    has_safety = bool(safety_re.search(lt))

    secure_match = (has_autonomy and (has_option or has_safety)) or (has_option and has_safety)

    announce_match = _stem_match(lt, (markers.get("Announce", {}).get("linguistic", [])))

    # Primary classification with tie-breakers
    # Prefer Mirror > Inquire > Secure > Announce when parent expresses emotion/concern
    parent_expressed_emotion = bool(re.search(r"\b(worried|scared|afraid|anxious|concern|don't trust|angry|nervous)\b", pt))

    step = None

    # Priority order: Mirror > Secure > Announce > Inquire (unless tie-breakers apply)
    if mirror_match:
        step = "Mirror"
        if _introduces_new_info(lt):
            reasons.append("Reflective stem detected but includes rebuttal/new info")
        else:
            reasons.append("Detected reflective stem; no new information added")
    elif secure_match and not announce_match:
        step = "Secure"
        reasons.append("Detected autonomy/option language; next steps implied")
    elif announce_match:
        step = "Announce"
        reasons.append("Detected recommendation language")
    elif inquire_match:
        step = "Inquire"
        reasons.append("Detected open-ended question; inviting elaboration")
    else:
        # No explicit markers matched — detect small talk/pleasantries first
        if _is_small_talk(lt):
            step = ""  # represent no AIMS step
            reasons.append("Rapport/pleasantries detected — no AIMS step attempted (allowed).")
        else:
            # Default: if parent expressed emotion, prefer Inquire to explore; else Announce
            if parent_expressed_emotion:
                step = "Inquire"
                reasons.append("Defaulted to Inquire due to parent emotion/concern cues")
            else:
                step = "Announce"
                reasons.append("Defaulted to Announce as safe baseline")

    # Tie-breaker: reflection then a question → Mirror if reflection is primary
    if mirror_match and inquire_match:
        # consider first sentence dominance
        first_sentence = lt.split("?")[0].split(".")[0]
        if _starts_with_any(first_sentence, ["it sounds like", "you're", "you are", "i'm hearing", "you feel", "you want", "i hear you", "i hear that", "i hear you're", "i hear that you're"]):
            step = "Mirror"
            reasons.append("Tie-breaker: reflection preceded question → Mirror")
        else:
            step = "Inquire"
            reasons.append("Tie-breaker: question primary → Inquire")

    # Tie-breaker: if both Inquire and strengthened Secure cues are present, prefer Secure
    if inquire_match and secure_match:
        step = "Secure"
        reasons.append("Preference question within options/safety context → Secure")

    # If only autonomy phrase present but no concrete options/resources, remain Announce
    if step == "Announce" and has_autonomy and not (has_option or has_safety):
        reasons.append("Autonomy phrase present but no concrete options → remain Announce")

    return ClassificationResult(step=step, reasons=reasons)


def _introduces_new_info(lt: str) -> bool:
    """Detect if clinician text introduces new factual info or rebuttal after a reflection.
    Very simple heuristic: presence of 'but', statistics-like tokens, or phrases like 'the data shows'.
    """
    if " but " in lt:
        return True
    if re.search(r"\b(data|evidence|study|studies|statistics|percent|%|risk)\b", lt):
        return True
    if "the data shows" in lt or "that's not true" in lt:
        return True
    return False


def score_step(step: str, parent_last: str, clinician_last: str, mapping: Dict[str, Any]) -> ScoreResult:
    """Score 0–3 based on mapping heuristics per step.

    This is a lightweight heuristic implementation to support unit tests and
    provide deterministic scoring. It is not intended to be exhaustive.
    """
    lt = (clinician_last or "").strip().lower()
    pt = (parent_last or "").strip().lower()
    reasons: List[str] = []
    score = 2  # start at 2 as 'decent', then adjust

    if step == "Mirror":
        # Penalize if introduces new info or rebuttal
        if _introduces_new_info(lt):
            score = 1
            reasons.append("Reflection included rebuttal/new info → penalized")
        # Bonus if includes a check for accuracy
        if re.search(r"did i get that right|is that right|did i capture", lt):
            score = min(3, score + 1)
            reasons.append("Included check for accuracy")
        # If no reflective stems, score low
        if not (_starts_with_any(lt, ["it sounds like", "you're", "you are", "i'm hearing", "you feel", "you want"])):
            score = min(score, 1)
            reasons.append("Weak/absent reflective stem")

    elif step == "Inquire":
        open_q = lt.endswith("?") or _starts_with_any(lt, ["what ", "how "])
        leading = bool(re.search(r"\b(don't|isn't it|right\?)\b", lt)) or "myth" in lt
        if not open_q:
            score = 1
            reasons.append("Not clearly open-ended")
        if leading:
            score = min(score, 1)
            reasons.append("Leading/judgmental phrasing")
        if open_q and not leading and len(lt) < 180:
            score = max(score, 2)
            reasons.append("Clear open question with decent tone")

    elif step == "Announce":
        # Expect recommendation + brief rationale; brevity rewarded
        has_reco = _stem_match(lt, ["i recommend", "it's time for", "due for", "today we will", "my recommendation is"])
        invite = bool(re.search(r"how does that sound|what do you think|questions\??", lt))
        rationale = bool(re.search(r"protect|outbreak|safety|safe|helps prevent|risk", lt))
        if not has_reco:
            score = 1
            reasons.append("No clear recommendation")
        if has_reco and rationale:
            score = max(score, 2)
            reasons.append("Included brief rationale")
        if invite:
            score = min(3, score + 1)
            reasons.append("Invited dialogue")

    elif step == "Secure":
        autonomy = _stem_match(lt, [
            "it's your decision", "i'm here to support", "it's your call", "up to you", "your choice"
        ])
        options = bool(re.search(
            r"\b("
            r"we can (do it|give it|get it|do the shot|schedule|wait|hold off|review|go over|share|check in)"
            r"|do it (today|now)"
            r"|today or (later|next week)"
            r"|now or later"
            r"|options include"
            r"|prefer"
            r"|handout"
            r"|follow-?up"
            r"|check in"
            r"|schedule"
            r")\b",
            lt,
        ))
        safety = bool(re.search(r"\b(what to expect|watch for|reach (out|me)|call if|how to reach|fever|redness|soreness|tylenol|acetaminophen|ibuprofen)\b", lt))
        if autonomy and options:
            score = max(score, 2)
            reasons.append("Autonomy affirmed with concrete option(s)")
        if safety:
            score = min(3, score + 1)
            reasons.append("Included safety-netting")
        if not autonomy and not options:
            score = 1
            reasons.append("Missing autonomy and options")

    # Clamp score between 0 and 3
    score = max(0, min(3, int(score)))
    return ScoreResult(score=score, reasons=reasons)


def evaluate_turn(parent_last: str, clinician_last: str, mapping: Dict[str, Any]) -> Dict[str, Any]:
    cls = classify_step(parent_last, clinician_last, mapping)

    # Handle rapport/pleasantries (no AIMS step attempted)
    if cls.step not in AIMS_STEPS:
        # Provide neutral feedback and a gentle forward suggestion; keep score integer for type consistency
        tips: List[str] = [
            "When you're ready, lead with a brief Announce specific to the vaccine and timing."
        ]
        return {
            "step": None,  # omit in UI; treated as non-step by callers
            "score": 0,
            "reasons": [
                "Rapport/pleasantries — no AIMS step attempted (allowed anytime)."
            ],
            "tips": tips,
        }

    scr = score_step(cls.step, parent_last, clinician_last, mapping)

    # Context-sensitive coaching tips: only include when an actionable improvement is evident.
    tips: List[str] = []
    lt = (clinician_last or "").strip().lower()
    if scr.score < 3:
        if cls.step == "Inquire":
            # Determine openness/why/leading to select a relevant tip
            open_q = lt.endswith("?") or lt.startswith("what ") or lt.startswith("how ")
            used_why = lt.startswith("why ") or " why " in lt
            leading = bool(re.search(r"\b(don't|isn't it|right\?)\b", lt)) or ("myth" in lt)
            if used_why or not open_q:
                tips.append("Prefer what and how questions; avoid why when it can feel accusatory.")
            elif leading:
                tips.append("Avoid leading or judgmental phrasing; use neutral, open framing.")
            else:
                # They asked a decent open question but weren't perfect — suggest a next-level skill
                tips.append("Ask, then pause. Silence helps.")
        elif cls.step == "Mirror":
            if _introduces_new_info(lt):
                tips.append("Reflect without adding new information or rebuttal; keep it brief and nonjudgmental.")
            elif not re.search(r"did i get that right|is that right|did i capture", lt):
                tips.append("End with a quick check for accuracy: 'Did I get that right?'")
        elif cls.step == "Announce":
            has_reco = _stem_match(lt, ["i recommend", "it's time for", "due for", "today we will", "my recommendation is"])
            invite = bool(re.search(r"how does that sound|what do you think|questions\??", lt))
            rationale = bool(re.search(r"protect|outbreak|safety|safe|helps prevent|risk", lt))
            if not has_reco:
                tips.append("Lead with a clear, brief recommendation specific to the vaccine and timing.")
            elif not rationale:
                tips.append("Add a short, parent-relevant reason (safety/benefit) in plain language.")
            elif not invite:
                tips.append("Invite dialogue with a brief opener, e.g., 'How does that sound?'")
        elif cls.step == "Secure":
            autonomy = _stem_match(lt, ["it's your decision", "i'm here to support"])
            options = bool(re.search(r"\b(we can|options include|prefer|today|later|handout|follow-?up)\b", lt))
            safety = bool(re.search(r"what to expect|watch for|reach me|call if|how to reach", lt))
            if not autonomy:
                tips.append("Affirm autonomy explicitly: 'It's your decision; I'm here to support you.'")
            if not options:
                tips.append("Offer a concrete next step (e.g., do it today or review a handout and check in next week).")
            if not safety:
                tips.append("Add a quick safety-net about what to expect and how to reach you.")

    # Keep tips concise: at most one highly relevant suggestion
    if len(tips) > 1:
        tips = tips[:1]

    return {
        "step": cls.step,
        "score": scr.score,
        "reasons": scr.reasons if scr.reasons else cls.reasons,
        "tips": tips,
    }
