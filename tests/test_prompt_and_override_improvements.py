import pytest

from app.prompts.aims import build_unified_classify_prompt, get_classify_system_instruction

# ---------------------------------------------------------------------------
# Test that the prompts contain the "best of both worlds" clinical logic
# ---------------------------------------------------------------------------

class TestPromptContent:

    def test_unified_v2_contains_triple_move(self):
        """unified_classify_v2.txt must contain the Triple-Move logic."""
        prompt = build_unified_classify_prompt(
            person_last="test",
            clinician_last="test",
            prior_announced=True,
            prior_phase="Secure",
            context_turns=3
        )
        assert "Triple-Move" in prompt
        assert "Mirror+Secure+Inquire" in prompt

    def test_unified_v2_contains_semantic_inquire(self):
        """unified_classify_v2.txt must define Inquire by functional goal, not punctuation."""
        prompt = build_unified_classify_prompt(
            person_last="test",
            clinician_last="test",
            prior_announced=True,
            prior_phase="Secure",
            context_turns=3
        )
        assert "functional goal" in prompt.lower()
        # The prompt uses "(statement or question)" and "NOT Inquire (CRITICAL)" section
        assert "statement or question" in prompt.lower()
        assert "not inquire (critical)" in prompt.lower()

    def test_unified_v2_contains_common_misclassifications(self):
        """unified_classify_v2.txt must contain the Common Misclassifications section."""
        prompt = build_unified_classify_prompt(
            person_last="test",
            clinician_last="test",
            prior_announced=True,
            prior_phase="Secure",
            context_turns=3
        )
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

    def test_unified_v2_has_new_json_structure(self):
        """unified_classify_v2.txt must use the step_feedback JSON structure."""
        prompt = build_unified_classify_prompt(
            person_last="test",
            clinician_last="test",
            prior_announced=True,
            prior_phase="Secure",
            context_turns=3
        )
        assert "step_feedback" in prompt
        assert "tone" in prompt
        assert "praise|improvement" in prompt or "praise" in prompt

    def test_system_instruction_has_feedback_tone_rules(self):
        """aims_system_instruction.txt must define praise/improvement tone rules."""
        instruction = get_classify_system_instruction()
        assert "tone" in instruction.lower()
        assert "praise" in instruction.lower()
        assert "improvement" in instruction.lower()

    def test_prompt_contains_status_question_rule(self):
        """Both prompts should handle trailing status questions as Announce."""
        v2 = build_unified_classify_prompt(
            person_last="test",
            clinician_last="test",
            prior_announced=True,
            prior_phase="Secure",
            context_turns=3
        )
        sys = get_classify_system_instruction()
        assert "status question" in v2.lower()
        assert "status question" in sys.lower()
        assert "not inquire" in v2.lower()
        assert "not inquire" in sys.lower()
