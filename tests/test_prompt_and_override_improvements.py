"""
Tests for the prompt quality and override-logic improvements.

Covers:
- recent_context is included in the unified classify prompt
- correct_inquire_to_secure: no longer flips short messages or messages with '?'
- correct_inquire_to_secure: still flips long, question-free, strongly-didactic lectures
- Pseudo-Secure gate: 60-word threshold (not 30)
- Pseudo-Secure gate: skipped when the message contains a '?' (dialogue invite)
- unified_classify.txt contains the scoring rubric and examples
"""
import pytest

from app.models import Coaching, ClassifierResult
from app.services.classifier_service import ClassifierService
from app.services.coach_post import AimsPostProcessor
from app.prompts.aims import build_unified_classify_prompt


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_svc() -> ClassifierService:
    return ClassifierService(project_id="t", location="us-central1", model_id="t")


def _result(step: str, score: int = 2, steps: list = None) -> ClassifierResult:
    return ClassifierResult(
        is_small_talk=False,
        is_vaccine_relevant=True,
        aims=Coaching(step=step, steps=steps or [step], score=score, reasons=[], tips=[]),
        safety_flags=[],
        person_topic=None,
        reasoning="",
    )


def _payload(step: str, score: int = 2) -> dict:
    return {"step": step, "score": score, "reasons": [], "tips": []}


# ---------------------------------------------------------------------------
# recent_context is threaded into the prompt
# ---------------------------------------------------------------------------

class TestRecentContextInPrompt:

    def test_recent_context_appears_in_rendered_prompt(self):
        """recent_context value should appear verbatim in the rendered prompt."""
        ctx = "Clinician: How are you?\nPerson: I have concerns about the MMR."
        prompt = build_unified_classify_prompt(
            person_last="I worry about side effects.",
            clinician_last="It sounds like you are worried.",
            prior_announced=True,
            prior_phase="InquireMirror",
            context_turns=3,
            recent_context=ctx,
        )
        assert ctx in prompt, "recent_context text should appear in rendered prompt"

    def test_no_context_shows_first_turn_placeholder(self):
        """An empty recent_context should render the first-turn placeholder."""
        prompt = build_unified_classify_prompt(
            person_last="Hello.",
            clinician_last="Hi there.",
            prior_announced=False,
            prior_phase="PreAnnounce",
            context_turns=3,
            recent_context="",
        )
        assert "first turn" in prompt.lower() or "none" in prompt.lower()

    def test_prompt_contains_scoring_rubric(self):
        """The rendered prompt must include the 0-3 scoring rubric."""
        prompt = build_unified_classify_prompt(
            person_last="",
            clinician_last="Test",
            prior_announced=False,
            prior_phase="PreAnnounce",
            context_turns=3,
        )
        # v2 prompt uses compact "3:" / "2:" / "1:" format
        assert "3:" in prompt and "2:" in prompt and "1:" in prompt
        assert "pseudo-Secure" in prompt.lower() or "pseudo" in prompt.lower()

    def test_prompt_contains_key_classification_rules(self):
        """The prompt should include key classification boundary rules."""
        prompt = build_unified_classify_prompt(
            person_last="",
            clinician_last="Test",
            prior_announced=False,
            prior_phase="PreAnnounce",
            context_turns=3,
        )
        # Mirror vs Secure boundary rule
        assert "mirror" in prompt.lower() and "secure" in prompt.lower()
        # Status question rule
        assert "vaccination status" in prompt.lower() or "status question" in prompt.lower()


# ---------------------------------------------------------------------------
# correct_inquire_to_secure: tightened guards
# ---------------------------------------------------------------------------

class TestCorrectInquireToSecure:

    def test_short_message_not_flipped(self):
        """Messages ≤ 40 words must NOT be flipped even with didactic language."""
        short_didactic = (
            "The data show the MMR vaccine is 97% effective. "
            "Clinical trials confirm safety."
        )  # < 40 words, no question
        payload = _payload("Inquire")
        result = AimsPostProcessor.correct_inquire_to_secure(payload, short_didactic)
        assert result["step"] == "Inquire", "Short message must not be flipped"

    def test_message_with_question_not_flipped(self):
        """Messages containing '?' must NOT be flipped regardless of length."""
        long_with_question = (
            "Research shows the MMR vaccine is very effective and clinical trials "
            "have demonstrated its safety profile over decades of use. "
            "The data show this is one of our most reliable tools for outbreak prevention. "
            "What are your thoughts about that?"
        )
        payload = _payload("Inquire")
        result = AimsPostProcessor.correct_inquire_to_secure(payload, long_with_question)
        assert result["step"] == "Inquire", "Message with question must not be flipped"

    def test_broad_tokens_alone_dont_flip(self):
        """Broad tokens (safe, schedule, dose, immune) must NOT trigger the flip."""
        broad_token_msg = (
            "The vaccine schedule is safe and the dose is appropriate for her immune system. "
            "We protect children by following the recommended schedule for each dose. "
            "Side effects are usually mild and immunity builds over time. "
            "This is standard practice at this visit."
        )
        payload = _payload("Inquire")
        result = AimsPostProcessor.correct_inquire_to_secure(payload, broad_token_msg)
        assert result["step"] == "Inquire", (
            "Broad tokens (safe, schedule, dose, immune) must not trigger Inquire→Secure"
        )

    def test_long_specific_didactic_lecture_is_flipped(self):
        """A long (>40 words), question-free message with strongly didactic language
        should still be flipped from Inquire to Secure."""
        lecture = (
            "The clinical trial data show that the MMR vaccine has a 97% efficacy rate. "
            "Randomized controlled studies have demonstrated no causal link to autism. "
            "Herd immunity requires approximately 95% coverage in the community. "
            "The evidence shows that vaccine-preventable diseases resurge when coverage drops. "
            "Statistics show that unvaccinated children face 35 times higher measles risk."
        )
        payload = _payload("Inquire")
        result = AimsPostProcessor.correct_inquire_to_secure(payload, lecture)
        assert result["step"] == "Secure", "Long didactic lecture should be flipped to Secure"

    def test_non_inquire_step_not_affected(self):
        """Should return unchanged if step is not Inquire."""
        payload = _payload("Mirror")
        result = AimsPostProcessor.correct_inquire_to_secure(payload, "Some long message with clinical trial data.")
        assert result["step"] == "Mirror"


# ---------------------------------------------------------------------------
# Pseudo-Secure gate: 60-word threshold + question exemption
# ---------------------------------------------------------------------------

class TestPseudoSecureGate:

    def test_message_under_60_words_not_penalized(self):
        """A Secure message under 60 words without autonomy cues should NOT be penalized."""
        svc = _make_svc()
        # 45 words, no autonomy cues, no question
        msg = (
            "Febrile seizures can be frightening to watch, but they are typically brief "
            "and do not cause lasting harm. The MMR vaccine does not increase that risk. "
            "We are here if anything happens and you can call us any time."
        )
        result = _result("Secure", score=3)
        out = svc._apply_overrides(result, msg)
        assert out.aims.score == 3, f"Under-60-word Secure should not be penalized, got {out.aims.score}"

    def test_message_over_60_words_no_autonomy_penalized(self):
        """A Secure message over 60 words with no autonomy cues and no question IS penalized."""
        svc = _make_svc()
        # > 60 words, no autonomy cues, no question
        msg = (
            "The MMR vaccine has been studied extensively for decades. It protects against "
            "measles, mumps, and rubella. Measles is highly contagious and can cause "
            "serious complications including encephalitis. Mumps can cause deafness in rare "
            "cases. Rubella poses a serious risk to unborn babies during pregnancy. "
            "The two-dose schedule provides approximately 97 percent protection against "
            "measles. Side effects are typically mild including a low-grade fever. "
            "The vaccine is recommended by all major health authorities worldwide."
        )
        result = _result("Secure", score=3)
        out = svc._apply_overrides(result, msg)
        assert out.aims.score == 1, f"Long Secure without autonomy should be penalized to 1, got {out.aims.score}"

    def test_message_over_60_words_with_question_not_penalized(self):
        """A long Secure message that contains a question (dialogue invite) is NOT penalized."""
        svc = _make_svc()
        # > 60 words, no autonomy cues, but HAS a question
        msg = (
            "The MMR vaccine has been studied extensively for decades. It protects against "
            "measles, mumps, and rubella. Measles is highly contagious and can cause "
            "serious complications including encephalitis. Mumps can cause deafness in rare "
            "cases. Rubella poses a serious risk to unborn babies during pregnancy. "
            "The two-dose schedule provides approximately 97 percent protection. "
            "Does that help address what you were worried about?"
        )
        result = _result("Secure", score=3)
        out = svc._apply_overrides(result, msg)
        assert out.aims.score == 3, (
            f"Secure with dialogue invite question should not be penalized, got {out.aims.score}"
        )

    def test_message_over_60_words_with_autonomy_not_penalized(self):
        """A long Secure message that contains autonomy cues is NOT penalized."""
        svc = _make_svc()
        msg = (
            "The MMR vaccine has been studied extensively for decades. It protects against "
            "measles, mumps, and rubella. Measles is highly contagious and can cause "
            "serious complications including encephalitis. Mumps can cause deafness in rare "
            "cases. Rubella poses a serious risk to unborn babies. It's your decision "
            "how you want to proceed and I'm here to support whatever you choose. "
            "We can do it today or schedule for next visit."
        )
        result = _result("Secure", score=3)
        out = svc._apply_overrides(result, msg)
        assert out.aims.score == 3, (
            f"Secure with autonomy cue should not be penalized, got {out.aims.score}"
        )
