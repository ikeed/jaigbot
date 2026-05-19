from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.aims_engine import evaluate_turn
from app.models import ClassifierResult, Coaching, StepFeedback
from app.services.chat_helpers import recent_context as build_recent_context
from app.services.coach_safety import detect_advice_patterns
from app.services.prompt_builders import AimsPromptBuilder
from app.vertex import VertexClient


class ClassifierService:
    """Unified classification service powered by Gemini.

    Consolidates AIMS classification, small-talk detection, relevance gating,
    and safety checking into a single LLM call. Provides deterministic
    fallbacks for reliability.
    """

    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        model_id: str,
        logger: Optional[logging.Logger] = None,
        temperature: float = 0.0,
        max_tokens: int = 500,
        client_cls: Any = VertexClient,
    ):
        self.project_id = project_id
        self.location = location
        self.model_id = model_id
        self.logger = logger or logging.getLogger(__name__)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.client_cls = client_cls

    async def classify_turn(
        self,
        *,
        clinician_message: str,
        person_last: str,
        history: List[Dict[str, str]],
        prior_announced: bool,
        prior_phase: str,
        mapping: Dict[str, Any],
        context_turns: int = 3,
        max_concerns: int = 3,
        inquired_concerns_list: List[str] = None,
        mirrored_concerns_list: List[str] = None,
    ) -> ClassifierResult:
        """Perform unified classification for a clinician turn."""
        
        # 1. Pre-filter with deterministic hints (optional, used as context)
        safety_hints = detect_advice_patterns(clinician_message)

        # 2. Build the prompt (split: static system instruction + lean per-turn prompt)
        # The system instruction contains the full AIMS rubric, scoring rules, and
        # reference data — identical across all requests (benefits from implicit caching).
        # The per-turn prompt contains only the dynamic conversation state.
        recent_ctx = build_recent_context(history, context_turns) if history else ""
        system_instruction = AimsPromptBuilder.get_classify_system_instruction()
        prompt = AimsPromptBuilder.build_classify_turn_prompt(
            person_last=person_last,
            clinician_last=clinician_message,
            prior_announced=prior_announced,
            prior_phase=prior_phase,
            recent_context=recent_ctx,
            inquired_concerns_list=inquired_concerns_list,
            mirrored_concerns_list=mirrored_concerns_list,
        )

        # 3. Call Gemini
        try:
            raw_json = await self._call_gemini_json(prompt, system_instruction=system_instruction)
            data = json.loads(self._strip_json_fences(raw_json))
            
            # Extract and normalize AIMS coaching
            aims_data = data.get("aims", {})
            steps = aims_data.get("steps") or []
            step = aims_data.get("step") # support both formats during transition
            
            if not step and steps:
                # Normalize steps array into single step string for legacy support
                if len(steps) == 1:
                    step = steps[0]
                elif "Announce" in steps and "Inquire" in steps and not prior_announced:
                    # First vaccine introduction + open concern-surfacing question
                    # in the same turn → compound Announce+Inquire.
                    step = "Announce+Inquire"
                elif "Announce" in steps and not prior_announced:
                    # First vaccine introduction: Announce dominates any other steps
                    # the LLM detected in the same turn.
                    step = "Announce"
                elif "Mirror" in steps and "Secure" in steps and "Inquire" not in steps:
                    step = "Mirror+Secure"
                elif "Mirror" in steps and "Inquire" in steps:
                    step = "Mirror+Inquire"
                elif "Secure" in steps and "Inquire" in steps and "Mirror" not in steps:
                    step = "Secure+Inquire"
                else:
                    # Pick the most "advanced" step or first one
                    priority = {"Secure": 5, "Mirror+Secure": 4, "Mirror+Inquire": 3, "Secure+Inquire": 3, "Mirror": 2, "Inquire": 1, "Announce": 0}
                    step = max(steps, key=lambda s: priority.get(s, -1), default=None)

            # Parse per-step feedback if present
            raw_sf = aims_data.get("step_feedback") or []
            step_feedback = []
            for sf in raw_sf:
                if isinstance(sf, dict) and sf.get("step") and sf.get("feedback"):
                    step_feedback.append(StepFeedback(
                        step=sf["step"],
                        feedback=sf["feedback"],
                        tone=sf.get("tone", "praise"),
                    ))

            aims_coaching = Coaching(
                step=step,
                steps=steps,
                score=aims_data.get("score"),
                reasons=aims_data.get("reasons") or [],
                tips=aims_data.get("tips") or [],
                step_feedback=step_feedback,
            )

            result = ClassifierResult(
                is_small_talk=data.get("is_small_talk", False),
                is_vaccine_relevant=data.get("is_vaccine_relevant", True),
                aims=aims_coaching,
                safety_flags=data.get("safety_flags") or [],
                person_topic=data.get("person_topic"),
                reasoning=data.get("reasoning")
            )
            
            # Clip tips to at most one as policy (parity with previous LLM path)
            if len(result.aims.tips) > 1:
                result.aims.tips = result.aims.tips[:1]

            # Post-processing overrides for known LLM weaknesses
            result = self._apply_overrides(result, clinician_message, prior_announced=prior_announced)
            return result

        except Exception as e:
            # Special exceptions (like 404/403) should bubble up to orchestrator
            # if they have a status_code or are from a known error class.
            status_code = getattr(e, "status_code", None)
            if status_code and status_code in {403, 404, 429}:
                raise e
                
            self.logger.error("Unified classification failed, falling back: %s", e)
            return self._get_deterministic_fallback(
                clinician_message, person_last, mapping, safety_hints
            )

    @staticmethod
    def _strip_json_fences(text: str) -> str:
        """Strip markdown ```json ... ``` fences from LLM output.

        Gemini 2.5 models frequently wrap JSON responses in markdown code
        fences even when the prompt asks for raw JSON.  This must be stripped
        before json.loads().
        """
        s = (text or "").strip()
        # Handle ```json ... ``` or ``` ... ```
        if s.startswith("```"):
            # Remove opening fence line
            first_newline = s.find("\n")
            if first_newline != -1:
                s = s[first_newline + 1:]
            else:
                s = s[3:]  # just "```" with no newline
            # Remove closing fence
            if s.rstrip().endswith("```"):
                s = s.rstrip()[:-3].rstrip()
        return s

    async def detect_endgame(
        self,
        *,
        history_text: str,
        announced: bool,
        inquired_concerns: List[str],
        mirrored_concerns: List[str],
        secured_concerns: List[str],
    ) -> Dict[str, Any]:
        """Call Gemini to detect if the session has reached a natural conclusion.

        TODO: Wire this into AimsCoachingHandler._check_end_game() as an LLM-based
        complement/replacement to the heuristic EndGameDetector. Currently prep work only.
        """
        prompt = AimsPromptBuilder.build_endgame_detector_prompt(
            history_text=history_text,
            announced=announced,
            inquired_concerns=inquired_concerns,
            mirrored_concerns=mirrored_concerns,
            secured_concerns=secured_concerns,
        )
        try:
            raw_json = await self._call_gemini_json(prompt)
            return json.loads(self._strip_json_fences(raw_json))
        except Exception as e:
            self.logger.error("Endgame detection failed: %s", e)
            return {"is_endgame": False, "reason": "detection_error"}

    async def _call_gemini_json(
        self, prompt: str, *, system_instruction: str | None = None
    ) -> str:
        """Call Gemini with JSON response expectation.

        Uses thinking_budget=128 to minimize thinking for classification tasks,
        reducing latency and cost. 128 is the minimum supported by gemini-2.5-pro;
        gemini-2.5-flash supports 0 but we use 128 for cross-model compatibility.

        When system_instruction is provided, the static AIMS rubric and reference
        data are passed separately from the per-turn prompt. This enables implicit
        context caching by the Gemini platform (the system_instruction prefix is
        identical across all classification requests in a session).
        """
        client = self.client_cls(
            project=self.project_id,
            region=self.location,
            model_id=self.model_id
        )
        return await client.generate_text_async(
            prompt,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            system_instruction=system_instruction,
            thinking_budget=128,
        )

    # Regex for vaccine-preventable disease names and vaccine-specific terms.
    # Used by the soft Announce detector to catch null-step classifications
    # where the LLM missed a soft vaccine introduction buried in a clinical
    # assessment (e.g. "I also like to make sure children are protected against
    # measles, whooping cough...").
    _SOFT_ANNOUNCE_RE = re.compile(
        r"\b(vaccin|immuniz|mmr|booster|measles|whooping|pertussis|"
        r"diphtheria|tetanus|polio|rotavirus|varicella|dtap|tdap|ipv|pcv|hib|"
        r"routine vaccines|routine shots)",
        re.IGNORECASE,
    )

    # Announce markers that indicate the primary intent is a recommendation or
    # first vaccine introduction, even when the message ends with a trailing
    # question like "How does that sound?" or a status question.
    # These prevent the Question Guard from overriding Announce → Inquire.
    _ANNOUNCE_MARKERS = [
        # Strong presumptive phrasing
        "i recommend", "it's time for", "it\u2019s time for", "due for",
        "today we will", "my recommendation is", "today we usually",
        "at this visit", "at the 2-month visit", "is due for", "routine vaccines",
        # Soft / contextual first-introduction patterns — these ARE Announce
        # even without presumptive phrasing. A trailing status question
        # ("Can I ask about vaccination status?") stays as Announce, not Inquire.
        "vaccination status", "vaccine status",
        "mmr vaccine", "measles protection",
        "is vaccines", "about vaccines", "talk about vaccines", "discuss vaccines",
        "vaccinated", "is vaccinated", "been vaccinated",
    ]

    # Strengthened Secure detection markers (Shared constants for parity)
    _SECURE_AUTONOMY_CUES = [
        "it's your decision", "it's your call", "up to you", "your choice",
        "i'm here to support", "informed and supported", "not rushed",
        "not pushed", "continue talking", "revisit any concerns",
        "you can decide", "how you want to proceed", "whatever you choose",
        "your decision to make", "entirely up to you",
        # Naturalistic autonomy phrasing
        "without pressure", "no pressure", "don't have to",
        "take your time", "not to corner", "isn't to corner",
    ]

    # Strong presumptive recommendation phrases that always indicate Announce,
    # used by the positive Announce detector below.
    _STRONG_ANNOUNCE_PHRASES = [
        "i recommend", "it's time for", "it\u2019s time for", "my recommendation is",
        "is due for", "due for", "today we will", "today we usually",
        "at this visit", "routine vaccines",
    ]

    # Check-in / landing / accuracy-check questions that are NOT Inquire.
    # These are part of the preceding Secure or Mirror step, not a new
    # concern-surfacing question.  Used by the Question Guard to avoid
    # inflating Secure/Mirror → Inquire.
    _CHECKIN_QUESTION_PHRASES = [
        # Secure landing checks
        "how does that land", "how does that sit", "how does that sound",
        "how does that feel", "does that make sense", "does that help",
        "does that address", "does that ease", "does that change",
        "what do you think about that", "how do you feel about that",
        "how do you feel hearing",
        # Mirror accuracy checks
        "have i got that right", "did i get that right",
        "did i capture that", "am i understanding", "am i getting that right",
        "am i reading that right", "is that right", "is that fair",
        "is that what you mean", "does that resonate",
    ]

    # Regex patterns for check-in questions with intervening words.
    # These catch natural variants like "How does that way of looking at it
    # land for you?" that exact substring matching misses.
    _CHECKIN_QUESTION_REGEXES = [
        re.compile(r"\bhow does (?:that|this|the \w+) .{0,50}\b(land|sit|sound|feel)\b"),
        re.compile(r"\bhow (?:are|were) you (?:feeling|doing)\b"),
        re.compile(r"\bdoes (?:that|this|the \w+) .{0,30}\b(help|address|ease|change)\b"),
        re.compile(r"\bwhat do you think (?:about|of) (?:that|this|the )\b"),
        re.compile(r"\bhow do you feel (?:about|hearing)\b"),
    ]

    @classmethod
    def _is_checkin_question(cls, msg_lower: str) -> bool:
        """Detect check-in/landing/accuracy-check questions.

        Uses both exact substring matching (for common phrases) and regex
        patterns (for natural variants with intervening words).
        """
        if any(phrase in msg_lower for phrase in cls._CHECKIN_QUESTION_PHRASES):
            return True
        return any(rx.search(msg_lower) for rx in cls._CHECKIN_QUESTION_REGEXES)

    # Closing-turn cues: detect wrapping-up turns that the LLM misclassifies
    # as Inquire because of proposal-style question phrasing ("Why don't we
    # book a follow-up?").  A message offering literature + follow-up +
    # autonomy is categorically Secure, not concern-surfacing Inquire.
    _CLOSING_LITERATURE_CUES = [
        "information", "literature", "read on your", "look over",
        "look it over", "take home", "materials", "handout", "brochure",
        "pamphlet", "review the information", "read at your",
        "send you home with",
    ]

    _CLOSING_FOLLOWUP_CUES = [
        "follow-up", "follow up", "book a", "come back",
        "next visit", "another appointment", "schedule a",
    ]

    # Sentence-level rebuttal detection: fires only when 'but' appears in the
    # same sentence as a reflective stem, indicating a direct "I hear you, but..."
    # pivot rather than an incidental 'but' in a separate educational clause.
    _REBUTTAL_STEMS = [
        "i hear you", "i understand", "it sounds like", "sounds like",
        "you're worried", "you feel", "i'm hearing", "what i'm hearing",
        "i hear that", "that makes sense", "that's fair", "that's valid",
        "that's understandable", "you're right that", "i know that",
    ]

    @classmethod
    def _has_rebuttal_but(cls, msg: str) -> bool:
        """True only when 'but' appears in the same sentence as a reflective stem.

        Splits on sentence boundaries so that 'but' in a later educational
        clause (e.g. '...but serious reactions are rare') does not trigger
        the penalty for a valid mirror in a preceding sentence.
        """
        sentences = re.split(r'(?<=[.!?\n])\s+', msg.lower())
        for sent in sentences:
            if ' but ' in sent and any(stem in sent for stem in cls._REBUTTAL_STEMS):
                return True
        return False

    def _apply_overrides(
        self,
        result: ClassifierResult,
        message: str,
        *,
        prior_announced: bool = False,
    ) -> ClassifierResult:
        """Apply deterministic overrides to common LLM misclassifications."""
        msg = (message or "").strip()
        msg_lower = msg.lower()

        # Soft Announce detector: catches two patterns the LLM commonly
        # misclassifies when Announce hasn't happened yet:
        #
        # (a) LLM returns null (rapport) but vaccine content is present —
        #     e.g. long clinical assessment ending with "I also like to make
        #     sure children are protected against measles, whooping cough..."
        #
        # (b) LLM returns Inquire but Announce hasn't happened yet and vaccine
        #     content is present — e.g. "I'm more interested in hearing your
        #     thoughts around vaccines for Carter."  Under AIMS, any first
        #     mention of vaccines (even embedded in an invite for concerns) is
        #     part of the Announce step, not a standalone Inquire.
        if not prior_announced and self._SOFT_ANNOUNCE_RE.search(msg):
            is_null_step = not result.aims.step
            is_inquire_pre_announce = (
                result.aims.step == "Inquire"
                and "Announce" not in result.aims.steps
            )
            if is_null_step or is_inquire_pre_announce:
                result.aims.step = "Announce"
                result.aims.steps = ["Announce"]
                result.aims.score = 1
                result.is_small_talk = False
                label = "null" if is_null_step else "Inquire"
                result.aims.reasons = [
                    f"You introduced vaccines softly — try a more direct recommendation to strengthen the Announce"
                ] + list(result.aims.reasons or [])
                result.aims.tips = [
                    "Try a presumptive recommendation "
                    "(e.g. \"It\u2019s time for [vaccine] today \u2014 how does that sound?\")."
                ]
                return result

        # Positive Announce detector: if the message contains unambiguous recommendation
        # language but the LLM didn't classify as Announce, add it.
        # This catches cases where the LLM focuses on a trailing Inquire and misses
        # a clear recommendation earlier in the same turn (e.g. "What I recommend for
        # kids this age is... what are your thoughts?").
        if result.aims.step != "Announce" and "Announce" not in result.aims.steps:
            if any(phrase in msg_lower for phrase in self._STRONG_ANNOUNCE_PHRASES):
                result.aims.steps = ["Announce"] + result.aims.steps
                result.aims.step = "Announce"
                result.is_small_talk = False  # Can't be small talk if it's Announce
                if not any("recommend" in r.lower() or "announce" in r.lower() for r in result.aims.reasons):
                    result.aims.reasons.insert(0, "Detected recommendation language \u2192 Announce")

        # Question Guard: prevent Announce/Secure from being kept when message
        # ends with '?' but has no announce language (trailing questions are Inquire).
        # Skip when strong Announce language is present OR when vaccine content is
        # detected (any message about specific vaccines is an Announce, regardless
        # of whether it matches the _ANNOUNCE_MARKERS keyword list exactly).
        # Also skip when the trailing question is a check-in or accuracy check
        # ("How does that land?", "Have I got that right?") — these are part of
        # the Secure or Mirror step, not concern-surfacing Inquire.
        if msg.endswith("?") and (result.aims.step in {"Announce", "Secure"} or "Announce" in result.aims.steps or "Secure" in result.aims.steps):
            # Check-in exemption: if the trailing question is a landing/accuracy
            # check, it is NOT Inquire — skip the guard entirely.
            _is_checkin = self._is_checkin_question(msg_lower)
            if _is_checkin:
                pass  # Leave step as-is; the question is part of Secure/Mirror
            else:
                # _SOFT_ANNOUNCE_RE only overrides the guard for multi-sentence messages
                # where vaccine content appears in an introductory body before the question.
                # A single-sentence question like "How are you feeling about today's vaccines?"
                # should still be flipped to Inquire; it is not a vaccine introduction.
                _msg_body = msg.rstrip("?").rstrip()
                _is_multi_sentence = bool(re.search(r'[.!\n]', _msg_body))
                _step_is_announce = result.aims.step == "Announce" or "Announce" in result.aims.steps
                has_announce_language = (
                    any(m in msg_lower for m in self._ANNOUNCE_MARKERS)
                    or (_is_multi_sentence and _step_is_announce and bool(self._SOFT_ANNOUNCE_RE.search(msg)))
                )
                if not has_announce_language:
                    # If it doesn't have announce markers but was called Announce/Secure and ends in ?, 
                    # ensure Inquire is present.
                    if result.aims.step in {"Announce", "Secure"}:
                        result.aims.step = "Inquire"
                    if "Inquire" not in result.aims.steps:
                        result.aims.steps.append("Inquire")
                    
                    if result.aims.score is not None:
                        result.aims.score = min(2, result.aims.score)

        # Check-in deflation: if the LLM returned a compound step with
        # Inquire (e.g. Mirror+Inquire, Secure+Inquire) but the only question
        # is a check-in/accuracy check, strip the Inquire component.
        # This catches cases the Question Guard can't — the guard only fires
        # for Announce/Secure, but the LLM can return Mirror+Inquire directly.
        if "Inquire" in (result.aims.steps or []) and len(result.aims.steps) > 1:
            if self._is_checkin_question(msg_lower):
                clean_steps = [s for s in result.aims.steps if s != "Inquire"]
                if clean_steps:
                    result.aims.steps = clean_steps
                    result.aims.step = clean_steps[0] if len(clean_steps) == 1 else result.aims.step.replace("+Inquire", "")

        # Closing-turn override: must be AFTER Question Guard so it is not
        # undone.  A message the LLM labelled Inquire that wraps up the visit
        # with literature + follow-up + autonomy is a Secure turn — the
        # question-style phrasing ("Why don't we book a follow-up?") is a
        # proposal, not concern-surfacing.
        if result.aims.step == "Inquire" and prior_announced:
            _has_lit = any(cue in msg_lower for cue in self._CLOSING_LITERATURE_CUES)
            _has_fu  = any(cue in msg_lower for cue in self._CLOSING_FOLLOWUP_CUES)
            _has_aut = any(cue in msg_lower for cue in self._SECURE_AUTONOMY_CUES)
            if sum([_has_lit, _has_fu, _has_aut]) >= 2:
                result.aims.step = "Secure"
                result.aims.steps = ["Secure"]
                result.aims.score = 2
                result.aims.reasons = [
                    "This turn wraps up with literature, follow-up, and/or autonomy support \u2014 classified as Secure"
                ] + list(result.aims.reasons or [])
                result.aims.tips = []

        # Mirror+BUT penalty: only fires when 'but' co-occurs with a reflective stem
        # in the SAME SENTENCE (direct pivot like "I hear you, but...").
        # Does NOT fire for 'but' in a separate educational clause, and is exempt
        # for Mirror+Secure where educational content is the intended Secure component.
        _is_mirror_step = (
            result.aims.step in {"Mirror", "Mirror+Inquire"}
            or ("Mirror" in result.aims.steps and result.aims.step not in {"Mirror+Secure"})
        )
        if _is_mirror_step and self._has_rebuttal_but(msg):
            result.aims.score = min(1, result.aims.score or 0)
            if not any("rebuttal" in r.lower() for r in result.aims.reasons):
                result.aims.reasons.append("Your reflection included a direct rebuttal ('but') in the same sentence — try separating the reflection from the education")

        # Detect pseudo-Secure (data-dumping/persuasion without autonomy support).
        # Only fires when the message is long (60+ words) AND contains no autonomy cues
        # AND contains no question (a dialogue invite like "Does that make sense?" signals
        # the clinician is NOT just lecturing).
        # Mirror+Secure is exempt: it explicitly combines Mirror and Secure content, so the
        # message will naturally be longer and have both reflective and educational sections.
        if (result.aims.step == "Secure" or "Secure" in result.aims.steps) and result.aims.step != "Mirror+Secure":
            has_autonomy = any(cue in msg_lower for cue in self._SECURE_AUTONOMY_CUES)
            has_question = "?" in msg
            if not has_autonomy and not has_question and len(msg.split()) > 60:
                result.aims.score = min(1, result.aims.score or 0)
                if not any("persuasion" in r.lower() for r in result.aims.reasons):
                    result.aims.reasons.append("You shared a lot of information without acknowledging their autonomy — try adding an explicit partnership statement (e.g., 'It's your decision').")

        return result

    def _get_deterministic_fallback(
        self,
        clinician_message: str,
        person_last: str,
        mapping: Dict[str, Any],
        safety_hints: List[str]
    ) -> ClassifierResult:
        """Invoke the original deterministic engine as a fallback."""
        
        fb = evaluate_turn(person_last, clinician_message, mapping)
        
        # Map deterministic 'evaluate_turn' result to ClassifierResult
        reasons = fb.get("reasons", [])
        if "fallback" not in reasons:
            reasons.append("fallback")
            
        aims_coaching = Coaching(
            step=fb.get("step"),
            score=fb.get("score", 2),
            reasons=reasons,
            tips=fb.get("tips", [])
        )
        
        return ClassifierResult(
            is_small_talk=False, # Fallback doesn't explicitly detect this well
            is_vaccine_relevant=True,
            aims=aims_coaching,
            safety_flags=safety_hints,
            reasoning="deterministic fallback"
        )
