from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.models import ClassifierResult, Coaching
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
        parent_last: str,
        history: List[Dict[str, str]],
        prior_announced: bool,
        prior_phase: str,
        mapping: Dict[str, Any],
        context_turns: int = 3,
        max_concerns: int = 3,
    ) -> ClassifierResult:
        """Perform unified classification for a clinician turn."""
        
        # 1. Pre-filter with deterministic hints
        from app.services.coach_safety import detect_advice_patterns
        safety_hints = detect_advice_patterns(clinician_message)

        # 2. Build the unified prompt
        markers = ((mapping or {}).get("meta", {}) or {}).get("per_step_classification_markers", {})
        markers_text = AimsPromptBuilder.markers_text(markers)
        recent_ctx = AimsPromptBuilder.recent_context(history, context_turns * 2)
        parent_recent_concerns = AimsPromptBuilder.extract_recent_concerns(history, max_concerns)

        prompt = AimsPromptBuilder.build_unified_classify_prompt(
            mapping_markers_text=markers_text,
            recent_ctx=recent_ctx,
            parent_recent_concerns=parent_recent_concerns,
            parent_last=parent_last,
            clinician_last=clinician_message,
            prior_announced=prior_announced,
            prior_phase=prior_phase,
            context_turns=context_turns,
            safety_hints=safety_hints,
        )

        # 3. Call Gemini
        try:
            raw_json = await self._call_gemini_json(prompt)
            data = json.loads(raw_json)
            
            # Extract and normalize AIMS coaching
            aims_data = data.get("aims", {})
            aims_coaching = Coaching(
                step=aims_data.get("step"),
                score=aims_data.get("score"),
                reasons=aims_data.get("reasons") or [],
                tips=aims_data.get("tips") or []
            )

            result = ClassifierResult(
                is_small_talk=data.get("is_small_talk", False),
                is_vaccine_relevant=data.get("is_vaccine_relevant", True),
                aims=aims_coaching,
                safety_flags=data.get("safety_flags") or [],
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
                clinician_message, parent_last, mapping, safety_hints
            )

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

    # Announce markers that indicate the primary intent is a recommendation,
    # even when the message ends with a dialogue-inviting question like
    # "How does that sound?".
    _ANNOUNCE_MARKERS = [
        "i recommend", "it's time for", "it\u2019s time for", "due for",
        "today we will", "my recommendation is",
    ]

    def _apply_overrides(self, result: ClassifierResult, message: str) -> ClassifierResult:
        """Apply deterministic overrides to common LLM misclassifications."""
        # AIMS step override for questions (Question Guard)
        # Skip when strong Announce language is present — trailing questions
        # like "How does that sound?" are dialogue-inviting, not Inquire.
        msg = (message or "").strip()
        if msg.endswith("?") and (result.aims.step in {"Announce", "Secure"}):
            lt = msg.lower()
            has_announce_language = any(m in lt for m in self._ANNOUNCE_MARKERS)
            if not has_announce_language:
                result.aims.step = "Inquire"
                if result.aims.score is not None:
                    result.aims.score = min(2, result.aims.score)
        
        # Score normalization (ensure 0-3 as per prompt instructions, or 1-5 as per legacy)
        # Note: prompt says 0-3, Coaching model says 0-3. Legacy engine uses 1-5.
        # We'll stick to what the prompt produces.
        
        return result

    def _get_deterministic_fallback(
        self,
        clinician_message: str,
        parent_last: str,
        mapping: Dict[str, Any],
        safety_hints: List[str]
    ) -> ClassifierResult:
        """Invoke the original deterministic engine as a fallback."""
        from app.aims_engine import evaluate_turn
        
        fb = evaluate_turn(parent_last, clinician_message, mapping)
        
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
