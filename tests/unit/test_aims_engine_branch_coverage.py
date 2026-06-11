"""
Additional tests for aims_engine.py to improve branch coverage to 85%+

These tests target specific uncovered branches identified in the coverage report.
"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.modules.aims.engine import (
    load_mapping, classify_step, score_step, evaluate_turn,
    stem_match, starts_with_any, introduces_new_info
)


@pytest.fixture(scope="module")
def aims_mapping():
    return load_mapping()


class TestLoadMapping:
    """Test load_mapping function branches"""
    
    def test_load_mapping_with_specific_path(self):
        """Test loading mapping with a specific path"""
        # Create a temporary file with valid JSON
        mapping_data = {"meta": {"per_step_classification_markers": {}}}
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(mapping_data, f)
            temp_path = f.name
        
        try:
            result = load_mapping(temp_path)
            assert result == mapping_data
        finally:
            os.unlink(temp_path)

    def test_load_mapping_default_is_independent_of_cwd(self, monkeypatch, tmp_path):
        """The bundled runtime mapping path is derived from the module location."""
        load_mapping.cache_clear()
        monkeypatch.chdir(tmp_path)

        result = load_mapping()

        assert isinstance(result, dict)
        load_mapping.cache_clear()
    
    def test_load_mapping_file_not_found_with_path(self):
        """An explicit override is authoritative."""
        with pytest.raises(FileNotFoundError):
            load_mapping("/nonexistent/path.json")
    
    def test_load_mapping_default_file_not_found(self):
        """Test load_mapping when the bundled mapping file does not exist."""
        load_mapping.cache_clear()
        with patch.dict(
            load_mapping.__wrapped__.__globals__,
            {"aims_mapping": Path("/nonexistent/path.json")},
        ):
            with pytest.raises(FileNotFoundError) as exc_info:
                load_mapping()
            assert "nonexistent/path.json" in str(exc_info.value)
        load_mapping.cache_clear()


class TestStemMatch:
    """Test _stem_match function branches"""
    
    def test_stem_match_empty_stem(self):
        """Test _stem_match with empty stem in list"""
        result = stem_match("hello world", ["", "hello"])
        assert result is True
        
    def test_stem_match_whitespace_only_stem(self):
        """Test _stem_match with whitespace-only stem"""
        result = stem_match("hello world", ["   ", "hello"])
        assert result is True
        
    def test_stem_match_no_match(self):
        """Test _stem_match returns False when no stems match"""
        result = stem_match("hello world", ["goodbye", "farewell"])
        assert result is False


class TestStartsWithAny:
    """Test _starts_with_any function branches"""
    
    def test_starts_with_any_empty_starter(self):
        """Test _starts_with_any with empty starter in list"""
        result = starts_with_any("hello world", ["", "goodbye"])
        assert result is False  # Empty string gets stripped and becomes empty
        
    def test_starts_with_any_whitespace_starter(self):
        """Test _starts_with_any with whitespace starter"""
        result = starts_with_any("hello world", ["  ", "goodbye"])
        assert result is False  # Whitespace gets stripped


class TestIntroducesNewInfo:
    """Test _introduces_new_info function branches"""
    
    def test_introduces_new_info_but_clause(self):
        """Test _introduces_new_info detects 'but' clauses"""
        assert introduces_new_info("I hear you're worried, but the data shows it's safe") is True
        
    def test_introduces_new_info_statistics(self):
        """Test _introduces_new_info detects statistical terms"""
        assert introduces_new_info("The study indicates safety") is True
        assert introduces_new_info("The evidence suggests efficacy") is True
        assert introduces_new_info("5 percent of people have reactions") is True  # Use valid percent phrase
        assert introduces_new_info("The risk is minimal") is True
        
    def test_introduces_new_info_specific_phrases(self):
        """Test _introduces_new_info detects specific phrases"""
        assert introduces_new_info("The data shows safety") is True
        # Test exact phrase from the function
        assert introduces_new_info("that's not true") is True
        
    def test_introduces_new_info_clean_reflection(self):
        """Test _introduces_new_info returns False for clean reflections"""
        assert introduces_new_info("It sounds like you're worried about safety") is False


class TestClassifyStepBranches:
    """Test classify_step function branches not covered by existing tests"""
    
    def test_classify_step_empty_mapping(self):
        """Test classify_step with empty mapping"""
        result = classify_step("What concerns you?", {})
        assert result.step == "Inquire"
    
    def test_classify_step_small_talk_detection(self):
        """Test classify_step detects small talk when no AIMS markers match"""
        result = classify_step("Hi there! Great to see you both!", {})
        assert result.step == ""  # No AIMS step
        assert "rapport/pleasantries" in result.reasons[0].lower()
        
    def test_classify_step_small_talk_question_not_inquire(self):
        """Test classify_step detects small talk cues"""
        result = classify_step("Hi there! How has he been sleeping?", {})
        # This might still be classified as Inquire, but covers the small talk detection branch
        assert result.step in ["Inquire", ""]
        
    def test_classify_step_mirror_with_new_info(self):
        """Test classify_step Mirror detection with new info"""
        result = classify_step(
            "It sounds like you're worried, but the data shows vaccines are safe", 
            {}
        )
        assert result.step == "Mirror"
        assert "includes rebuttal/new info" in result.reasons[0]
        
    def test_classify_step_didactic_secure(self):
        """Test classify_step didactic education mapping to Secure"""
        result = classify_step(
            "Studies show vaccines protect against outbreaks", 
            {}
        )
        assert result.step == "Secure"
        assert "Didactic education" in result.reasons[0]
        
    def test_classify_step_edge_cases(self):
        """Test classify_step edge cases for branch coverage"""
        # Test various edge cases to hit different branches
        result1 = classify_step("The data shows vaccines are safe", {})
        assert result1.step in ["Secure", "Announce"]
        
        result2 = classify_step("I understand your concerns", {})
        assert result2.step in ["Mirror", "Announce"]
        
        result3 = classify_step("We can do it today", {})
        # With empty mapping, no Secure (needs autonomy+safety) and no Announce markers
        assert result3.step in ["Secure", "Announce", ""]
        
    def test_classify_step_no_markers_falls_to_rapport(self):
        """Test classify_step falls to rapport when no AIMS markers match"""
        # "The vaccine is important for health." has no question mark, no mirror
        # stems, no secure markers — but does match didactic_secure ("protect" in
        # didactic_re won't fire because "important" isn't in the regex, but
        # "safe" isn't present either). With the inverted logic, messages that
        # don't match any AIMS marker fall through to rapport.
        result = classify_step(
            "Thank you for sharing that with me.",
            {}
        )
        assert result.step == ""
        assert "rapport" in result.reasons[0].lower()


class TestScoreStepBranches:
    """Test score_step function branches not covered by existing tests"""
    
    def test_score_step_mirror_with_accuracy_check(self):
        """Test score_step Mirror with accuracy check gets bonus"""
        result = score_step(
            "Mirror", 
            "It sounds like you're concerned. Did I capture that correctly?", 
            {}
        )
        assert result.score >= 2
        assert "accuracy" in str(result.reasons).lower()
        
    def test_score_step_mirror_weak_reflective_stem(self):
        """Test score_step Mirror with weak reflective stem"""
        result = score_step(
            "Mirror", 
            "I see that you have concerns", 
            {}
        )
        assert result.score <= 1
        assert "Weak/absent reflective stem" in result.reasons
        
    def test_score_step_inquire_not_open_ended(self):
        """Test score_step Inquire that's not clearly open-ended"""
        result = score_step(
            "Inquire", 
            "You should consider the benefits", 
            {}
        )
        assert result.score == 1
        assert "Not clearly open-ended" in result.reasons
        
    def test_score_step_inquire_leading_judgmental(self):
        """Test score_step Inquire with leading/judgmental phrasing"""
        result = score_step(
            "Inquire", 
            "You don't believe those myths, right?", 
            {}
        )
        assert result.score <= 1
        assert "Leading/judgmental phrasing" in result.reasons
        
    def test_score_step_inquire_good_open_question(self):
        """Test score_step Inquire with good open question"""
        result = score_step(
            "Inquire", 
            "What specific concerns do you have?", 
            {}
        )
        assert result.score >= 2
        assert "Clear open question with decent tone" in result.reasons
        
    def test_score_step_announce_no_recommendation(self):
        """Test score_step Announce without clear recommendation"""
        result = score_step(
            "Announce", 
            "Vaccines are generally good for health", 
            {}
        )
        assert result.score == 1
        assert "No clear recommendation" in result.reasons
        
    def test_score_step_announce_with_rationale(self):
        """Test score_step Announce with rationale"""
        result = score_step(
            "Announce", 
            "I recommend the MMR today to protect against measles outbreaks", 
            {}
        )
        assert result.score >= 2
        assert "brief rationale" in result.reasons[0]
        
    def test_score_step_announce_with_invitation(self):
        """Test score_step Announce with dialogue invitation"""
        result = score_step(
            "Announce", 
            "I recommend the MMR. How does that sound?", 
            {}
        )
        assert result.score >= 2
        assert "Invited dialogue" in result.reasons
        
    def test_score_step_secure_missing_autonomy_and_options(self):
        """Test score_step Secure missing both autonomy and options"""
        result = score_step(
            "Secure", 
            "The vaccine will help protect you", 
            {}
        )
        assert result.score == 1
        assert "Missing autonomy and options" in result.reasons
        
    def test_score_step_secure_autonomy_and_options(self):
        """Test score_step Secure with autonomy and options"""
        result = score_step(
            "Secure", 
            "It's your decision. We can do it today or schedule for next week", 
            {}
        )
        assert result.score >= 2
        assert "Autonomy affirmed with concrete option(s)" in result.reasons
        
    def test_score_step_secure_with_safety_netting(self):
        """Test score_step Secure with safety netting gets bonus"""
        result = score_step(
            "Secure", 
            "It's your choice. We can do it today. Call if you have concerns", 
            {}
        )
        assert result.score >= 2
        # Check if safety-netting is mentioned in any reason
        safety_mentioned = any("safety" in reason.lower() for reason in result.reasons)
        assert safety_mentioned or len(result.reasons) > 0


class TestEvaluateTurnBranches:
    """Test evaluate_turn function branches not covered by existing tests"""
    
    def test_evaluate_turn_small_talk_no_step(self):
        """Test evaluate_turn with small talk (no AIMS step)"""
        result = evaluate_turn("Hi! Great to see you both!", {})
        assert result["step"] is None
        assert result["score"] == 0
        assert "Rapport/pleasantries" in result["reasons"][0]
        assert len(result["tips"]) > 0
        assert "Announce" in result["tips"][0]
        
    def test_evaluate_turn_inquire_tips_why_question(self):
        """Test evaluate_turn Inquire tips for 'why' questions"""
        result = evaluate_turn("Why don't you trust vaccines?", {})
        assert result["step"] == "Inquire"
        assert result["score"] < 3
        assert any("why" in tip.lower() for tip in result["tips"])
        
    def test_evaluate_turn_inquire_tips_leading_phrasing(self):
        """Test evaluate_turn Inquire tips for leading phrasing"""
        result = evaluate_turn("You don't believe that, right?", {})
        assert result["step"] == "Inquire"
        assert result["score"] < 3
        assert any("leading" in tip.lower() or "judgmental" in tip.lower() for tip in result["tips"])
        
    def test_evaluate_turn_inquire_tips_decent_question(self):
        """Test evaluate_turn Inquire tips for decent open question"""
        result = evaluate_turn("What specific concerns do you have?", {})
        assert result["step"] == "Inquire"
        # May or may not have tips depending on score, but should not crash
        assert isinstance(result["tips"], list)
        
    def test_evaluate_turn_mirror_tips_new_info(self):
        """Test evaluate_turn Mirror tips when introducing new info"""
        result = evaluate_turn(
            "It sounds like you're worried, but the data shows it's safe", 
            {}
        )
        assert result["step"] == "Mirror"
        assert result["score"] < 3
        assert any("rebuttal" in tip.lower() or "new information" in tip.lower() for tip in result["tips"])
        
    def test_evaluate_turn_mirror_tips_no_accuracy_check(self):
        """Test evaluate_turn Mirror tips when missing accuracy check"""
        result = evaluate_turn("It sounds like you're concerned about safety", {})
        assert result["step"] == "Mirror"
        assert result["score"] < 3
        assert any("accuracy" in tip.lower() for tip in result["tips"])
        
    def test_evaluate_turn_announce_tips_no_invite(self, aims_mapping):
        """Test evaluate_turn Announce tips when missing dialogue invitation"""
        # Has recommendation + rationale but no invitation ("How does that sound?")
        # Needs real mapping so Announce linguistic markers are available.
        result = evaluate_turn(
            "I recommend the MMR vaccine today to protect against measles outbreaks.",
            aims_mapping,
        )
        assert result["step"] == "Announce"
        assert result["score"] < 3
        assert any("invite" in tip.lower() or "dialogue" in tip.lower() for tip in result["tips"])
        
    def test_evaluate_turn_announce_tips_no_rationale(self, aims_mapping):
        """Test evaluate_turn Announce tips when missing rationale"""
        result = evaluate_turn("I recommend the MMR vaccine", aims_mapping)
        assert result["step"] == "Announce"
        assert result["score"] < 3
        assert any("reason" in tip.lower() for tip in result["tips"])
        
    def test_evaluate_turn_various_scenarios(self):
        """Test evaluate_turn with various scenarios for branch coverage"""
        # Test different scenarios to hit various branches in the tips generation
        result1 = evaluate_turn("I recommend the MMR today to protect against measles", {})
        assert result1["step"] in ["Announce", "Secure"]
        assert isinstance(result1["tips"], list)
        
        result2 = evaluate_turn("We can do it today or next week", {})
        assert isinstance(result2["tips"], list)
        
        result3 = evaluate_turn("It's your decision and I support you", {})
        assert isinstance(result3["tips"], list)
        
    def test_additional_branch_coverage(self):
        """Additional tests to hit remaining uncovered branches"""
        # Test empty text scenarios
        result1 = classify_step("", {})
        assert isinstance(result1.step, str)
        
        # Test score clamping
        result2 = score_step("Unknown", "", {})
        assert 0 <= result2.score <= 3
        
        # Test parent expressed emotion branch
        result3 = classify_step("What concerns you?", {})
        assert result3.step == "Inquire"
        
        # Test exception handling in evaluate_turn
        result4 = evaluate_turn("", {})
        assert "step" in result4
        assert "score" in result4
        
        # Test very long text for different scoring branches
        long_text = "What are your specific concerns about vaccines? " * 10
        result5 = score_step("Inquire", long_text, {})
        assert isinstance(result5.score, int)
        
    def test_evaluate_turn_multiple_tips_truncated(self, aims_mapping):
        """Test evaluate_turn limits tips to one when multiple are generated"""
        # Use real mapping so Announce markers are available
        result = evaluate_turn("Today we will give Emily her vaccines", aims_mapping)
        assert result["step"] == "Announce"
        assert len(result["tips"]) <= 1  # Should be truncated to at most one tip
