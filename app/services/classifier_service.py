from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.aims_engine import evaluate_turn
from app.models import ClassifierResult, Coaching
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

        # 2. Build the unified prompt
        # Include recent conversation turns so the LLM can evaluate Mirror accuracy
        # and detect context that a single-turn view would miss.
        recent_ctx = build_recent_context(history, context_turns) if history else ""
        prompt = AimsPromptBuilder.build_unified_classify_prompt(
            person_last=person_last,
            clinician_last=clinician_message,
            prior_announced=prior_announced,
            prior_phase=prior_phase,
            context_turns=context_turns,
            recent_context=recent_ctx,
            inquired_concerns_list=inquired_concerns_list,
            mirrored_concerns_list=mirrored_concerns_list,
        )

        # 3. Call Gemini
        try:
            raw_json = await self._call_gemini_json(prompt)
            data = json.loads(raw_json)
            
            # Extract and normalize AIMS coaching
            aims_data = data.get("aims", {})
            steps = aims_data.get("steps") or []
            step = aims_data.get("step") # support both formats during transition
            
            if not step and steps:
                # Normalize steps array into single step string for legacy support
                if len(steps) == 1:
                    step = steps[0]
                elif "Mirror" in steps and "Inquire" in steps:
                    step = "Mirror+Inquire"
                else:
                    # Pick the most "advanced" step or first one
                    priority = {"Secure": 4, "Mirror+Inquire": 3, "Mirror": 2, "Inquire": 1, "Announce": 0}
                    step = max(steps, key=lambda s: priority.get(s, -1), default=None)

            aims_coaching = Coaching(
                step=step,
                steps=steps,
                score=aims_data.get("score"),
                reasons=aims_data.get("reasons") or [],
                tips=aims_data.get("tips") or []
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
            result = self._apply_overrides(result, clinician_message)
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
            return json.loads(raw_json)
        except Exception as e:
            self.logger.error("Endgame detection failed: %s", e)
            return {"is_endgame": False, "reason": "detection_error"}

    async def _call_gemini_json(self, prompt: str) -> str:
        """Call Vertex AI with JSON response expectation."""
        client = self.client_cls(
            project=self.project_id,
            region=self.location,
            model_id=self.model_id
        )
        # We don't use strict schema here yet to keep it flexible, 
        # but we expect JSON from the prompt instructions.
        return await client.generate_text_async(
            prompt,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
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
    ]

    # Strong presumptive recommendation phrases that always indicate Announce,
    # used by the positive Announce detector below.
    _STRONG_ANNOUNCE_PHRASES = [
        "i recommend", "it's time for", "it\u2019s time for", "my recommendation is",
        "is due for", "due for", "today we will", "today we usually",
        "at this visit", "routine vaccines",
    ]

    def _apply_overrides(self, result: ClassifierResult, message: str) -> ClassifierResult:
        """Apply deterministic overrides to common LLM misclassifications."""
        msg = (message or "").strip()
        msg_lower = msg.lower()

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
        # Skip when strong Announce language is present.
        if msg.endswith("?") and (result.aims.step in {"Announce", "Secure"} or "Announce" in result.aims.steps or "Secure" in result.aims.steps):
            has_announce_language = any(m in msg_lower for m in self._ANNOUNCE_MARKERS)
            if not has_announce_language:
                # If it doesn't have announce markers but was called Announce/Secure and ends in ?, 
                # ensure Inquire is present.
                if result.aims.step in {"Announce", "Secure"}:
                    result.aims.step = "Inquire"
                if "Inquire" not in result.aims.steps:
                    result.aims.steps.append("Inquire")
                
                if result.aims.score is not None:
                    result.aims.score = min(2, result.aims.score)

        # Mirror+BUT penalty (parity with prompt instruction and aims_engine)
        if result.aims.step in {"Mirror", "Mirror+Inquire"} or "Mirror" in result.aims.steps:
            if " but " in msg_lower:  # Only penalize immediate 'but' rebuttals in Mirror turns
                result.aims.score = min(1, result.aims.score or 0)
                if not any("rebuttal" in r.lower() for r in result.aims.reasons):
                    result.aims.reasons.append("Reflection included rebuttal/new info → penalized")

        # Detect pseudo-Secure (data-dumping/persuasion without autonomy support).
        # Only fires when the message is long (60+ words) AND contains no autonomy cues
        # AND contains no question (a dialogue invite like "Does that make sense?" signals
        # the clinician is NOT just lecturing).
        if result.aims.step == "Secure" or "Secure" in result.aims.steps:
            has_autonomy = any(cue in msg_lower for cue in self._SECURE_AUTONOMY_CUES)
            has_question = "?" in msg
            if not has_autonomy and not has_question and len(msg.split()) > 60:
                result.aims.score = min(1, result.aims.score or 0)
                if not any("persuasion" in r.lower() for r in result.aims.reasons):
                    result.aims.reasons.append("Secure score reduced: appears to be persuasion/data-dumping without explicit autonomy support.")

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
