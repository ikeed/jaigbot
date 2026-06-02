from app.prompts.aims import build_classify_turn_prompt, get_classify_system_instruction

# ---------------------------------------------------------------------------
# Test that the prompts contain the "best of both worlds" clinical logic
# ---------------------------------------------------------------------------

class TestPromptContent:
    def _active_classifier_prompt(self, **kwargs):
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
        assert "tone" in prompt
        assert "praise|improvement" in prompt or "praise" in prompt

    def test_system_instruction_has_feedback_tone_rules(self):
        """aims_system_instruction.txt must define praise/improvement tone rules."""
        instruction = get_classify_system_instruction()
        assert "tone" in instruction.lower()
        assert "praise" in instruction.lower()
        assert "improvement" in instruction.lower()

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
