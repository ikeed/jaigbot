from app.prompts.aims import (
    build_classify_turn_prompt,
    build_fallback_feedback_prompt,
    build_summary_analysis_prompt,
    get_classify_system_instruction,
)

# ---------------------------------------------------------------------------
# Test that the prompts contain the "best of both worlds" clinical logic
# ---------------------------------------------------------------------------

class TestPromptContent:
    @staticmethod
    def _active_classifier_prompt(**kwargs):
        return (
            get_classify_system_instruction()
            + "\n\n"
            + build_classify_turn_prompt(
                person_last=kwargs.get("person_last", "test"),
                clinician_last=kwargs.get("clinician_last", "test"),
                prior_announced=kwargs.get("prior_announced", True),
                prior_phase=kwargs.get("prior_phase", "Secure"),
                recent_context=kwargs.get("recent_context", ""),
            )
        )

    def test_active_classifier_prompt_contains_triple_move(self):
        """Active classifier prompts must contain the Triple-Move logic."""
        prompt = self._active_classifier_prompt()
        assert "Triple-Move" in prompt
        assert "Mirror+Secure+Inquire" in prompt

    def test_active_classifier_prompt_contains_semantic_inquire(self):
        """Active classifier prompts must define Inquire by functional goal, not punctuation."""
        prompt = self._active_classifier_prompt()
        assert "functional goal" in prompt.lower()
        # The prompt uses "(statement or question)" and "NOT Inquire (CRITICAL)" section.
        assert "statement or question" in prompt.lower()
        assert "not inquire (critical)" in prompt.lower()

    def test_active_classifier_prompt_contains_common_misclassifications(self):
        """Active classifier prompts must contain the Common Misclassifications section."""
        prompt = self._active_classifier_prompt()
        assert "COMMON MISCLASSIFICATIONS" in prompt

    def test_system_instruction_contains_triple_move(self):
        """aims_system_instruction.txt must contain the Triple-Move logic."""
        instruction = get_classify_system_instruction()
        assert "Triple-Move" in instruction
        assert "Mirror+Secure+Inquire" in instruction

    def test_system_instruction_contains_pseudo_secure_penalty(self):
        """aims_system_instruction.txt must contain the 50-word pseudo-Secure rule."""
        instruction = get_classify_system_instruction()
        assert "50 words" in instruction
        assert "pseudo-Secure" in instruction or "data-dump" in instruction

    def test_active_classifier_prompt_has_new_json_structure(self):
        """Active classifier prompts must use the step_feedback JSON structure."""
        prompt = self._active_classifier_prompt()
        assert "step_feedback" in prompt
        assert "observations" in prompt
        assert "feedback_items" in prompt
        assert "person_events" in prompt
        assert "resolution" in prompt
        assert "tone" in prompt
        assert "praise|improvement" in prompt or "praise" in prompt

    def test_system_instruction_has_feedback_tone_rules(self):
        """aims_system_instruction.txt must define praise/improvement tone rules."""
        instruction = get_classify_system_instruction()
        lower = instruction.lower()
        assert "tone" in lower
        assert "praise" in lower
        assert "improvement" in lower
        assert "past-tense second-person" in lower
        assert "ui labels it with `tip:`" in lower

    def test_system_instruction_contains_optional_semantic_contract(self):
        """Structured optional fields should be available for non-regex decisions."""
        instruction = get_classify_system_instruction().lower()
        assert "optional semantic fields" in instruction
        assert "open_concern_question_present" in instruction
        assert "feedback_items" in instruction
        assert "person_events" in instruction
        assert "remaining_active_concern" in instruction

    def test_system_instruction_prevents_tips_for_behavior_already_done(self):
        """Tips should target actual gaps, not already-successful behavior."""
        instruction = get_classify_system_instruction().lower()
        assert "do not suggest a behavior the clinician already performed" in instruction
        assert "if they asked an open concern question" in instruction
        assert "pausing" in instruction

    def test_person_topic_excludes_literature_followup_acceptance(self):
        """Prompts must not turn literature/follow-up agreement into autonomy concerns."""
        active = self._active_classifier_prompt(
            person_last="That sounds good. I will read it over at home and follow up.",
            clinician_last="I will give you written information and book a follow-up.",
            prior_announced=True,
            prior_phase="Secure",
        )
        sys = get_classify_system_instruction()
        for text in (active, sys):
            lower = text.lower()
            assert "person_topic" in lower
            assert "literature/follow-up agreement" in lower
            assert "autonomy" in lower
            assert "null" in lower

    def test_person_topic_includes_low_disease_risk_category(self):
        """Prompts need a category for 'disease feels gone' concerns."""
        active = self._active_classifier_prompt(
            person_last="I thought measles was basically gone. I haven't seen any cases.",
            clinician_last="What are your thoughts about MMR?",
            prior_announced=True,
            prior_phase="InquireMirror",
        )
        sys = get_classify_system_instruction()
        for text in (active, sys):
            lower = text.lower()
            assert "disease_risk" in lower
            assert "historical" in lower or "feels gone" in lower
            assert "effectiveness" in lower

    def test_feedback_prompt_warns_against_overstating_followup_logistics(self):
        """Coach feedback should not say a follow-up was scheduled unless it was explicit."""
        active = self._active_classifier_prompt(
            person_last="That sounds okay.",
            clinician_last="We can revisit it after she recovers.",
            prior_announced=True,
            prior_phase="Secure",
        )
        sys = get_classify_system_instruction()
        for text in (active, sys):
            lower = text.lower()
            assert "scheduled" in lower or "booked" in lower
            assert "revisit" in lower
            assert "explicitly" in lower

    def test_prompt_contains_status_question_rule(self):
        """Both prompts should handle trailing status questions as Announce."""
        active = self._active_classifier_prompt()
        sys = get_classify_system_instruction()
        assert "status question" in active.lower()
        assert "status question" in sys.lower()
        assert "not inquire" in active.lower()
        assert "not inquire" in sys.lower()

    def test_fallback_feedback_prompt_requires_specificity(self):
        """Fallback feedback prompt should ask the model to de-formulaize coaching."""
        prompt = build_fallback_feedback_prompt(
            context={
                "clinician_message": "I understand your concerns.",
                "person_last": "But is it required?",
                "fallback_coaching": {
                    "step": "Secure",
                    "score": 1,
                    "reasons": ["Secure before mirroring."],
                    "tips": ["Affirm autonomy explicitly."],
                },
            }
        )
        lower = prompt.lower()
        assert "refine the coaching for a fallback aims turn" in lower
        assert "avoid stock phrases" in lower
        assert "preserve the detected step and the score" in lower
        assert "step_feedback" in lower
        assert "do not suggest a behavior the clinician already performed" in lower
        assert 'ui labels it with "tip:"' in lower

    def test_classify_turn_prompt_renders_context_and_concern_lists(self):
        prompt = build_classify_turn_prompt(
            person_last="I thought measles was basically gone.",
            clinician_last="What worries you most about the MMR vaccine?",
            prior_announced=True,
            prior_phase="InquireMirror",
            recent_context="Doctor: We recommend the MMR today.\nAssistant: I thought measles was gone.",
            inquired_concerns_list=["disease_risk", "trust"],
            mirrored_concerns_list=["trust"],
        )
        assert "Doctor: We recommend the MMR today." in prompt
        assert "I thought measles was gone." in prompt
        assert "Inquired Concerns: disease_risk, trust" in prompt
        assert "Mirrored Concerns: trust" in prompt
        assert "Announced: true" in prompt
        assert "Phase: InquireMirror" in prompt

    def test_classify_turn_prompt_contains_person_topic_guardrails(self):
        prompt = build_classify_turn_prompt(
            person_last="That sounds good. I'll read it over and we can talk at the next appointment.",
            clinician_last="I'll send you home with some information and we can follow up.",
            prior_announced=True,
            prior_phase="Secure",
        )
        lower = prompt.lower()
        assert "set `person_topic` only for an active vaccine concern in person_last" in lower
        assert "use `null` for acceptance/closure language" in lower
        assert "schedule/attend a follow-up" in lower
        assert "disease_risk" in lower
        assert "do not force this into `effectiveness`" in lower

    def test_summary_analysis_prompt_contains_groundedness_rules(self):
        prompt = build_summary_analysis_prompt(
            metrics_blob='{"stepCoverage":{"Mirror":1},"runningAverage":{"Mirror":2.0}}',
            mapping_blob='{"meta":{}}',
            transcript="Doctor: hello\nAssistant: hi",
        )
        lower = prompt.lower()
        assert "metrics_blob" in lower
        assert "authoritative ground truth" in lower
        assert "never claim a step was" in lower
        assert "stepcoverage[step] > 0" in lower
        assert "do not invent concerns" in lower
        assert "strict json only" in lower
        assert "overall_commentary" in prompt
        assert "metric_notes" in prompt
        assert "status" in prompt
