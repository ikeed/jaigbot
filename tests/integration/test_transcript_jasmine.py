"""
Integration test: Jasmine/Sophia transcript replay (live LLM).

Replays the exact clinician and parent dialog from bug-report session
4315da9d-4c2f-4478-8c2d-c7e0be0f49db through the full coaching pipeline.
Only patient replies are scripted from the saved transcript; classification
and endgame detection use the real Vertex AI model.

This transcript regresses a specific failure: the parent accepted take-home
information plus follow-up, but the state tracker recorded that acceptance as
a new unmirrored autonomy concern. That false concern blocked endgame before
the detector could recognize the accepted_literature resolution.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.config import settings
from base import (
    ReplyOnlyGateway,
    LiveClassifyClient,
    TranscriptReplayTest,
    TurnExpectation,
)


# ---------------------------------------------------------------------------
# Transcript data
# ---------------------------------------------------------------------------

CLINICIAN_TURNS = [
    (
        "Hi Jasmine, it\u2019s good to see you and Sophia today. Two months can be a pretty exhausting stage, especially with your first baby, so we\u2019ll make sure we go through everything carefully. I\u2019ll check how Sophia\u2019s feeding, sleeping, growth, and development are going, and we can talk through any questions you\u2019ve had since bringing her home.\n\n"
        "I also see that today is the visit where Sophia is due for her 2-month immunizations. These vaccines help protect babies from some serious infections at an age when they\u2019re still very vulnerable."
    ),
    (
        "What concerns me most hearing that is how much thought and care you\u2019re putting into this. You\u2019re looking at this tiny little person who depends completely on you, and you want to be certain that anything we do is truly in her best interest and not more than her body can handle right now. Have I got that right?"
    ),
    (
        "You absolutely are protecting her by thinking carefully about these decisions, and you\u2019re the one who gets to decide what happens for Sophia. What I can tell you is that a healthy baby\u2019s immune system is already handling thousands of new exposures every day just from living in the world. The vaccines at this age are designed specifically for young infants and expose the immune system to a very small, controlled amount compared with what babies naturally encounter.\n\n"
        "The reason we give them early is because illnesses like whooping cough and meningitis can be especially dangerous in the first months of life, before babies have much protection of their own. Most babies do well with these vaccines \u2014 the common reactions are things like fussiness, sleepiness, or a sore leg for a day or two.\n\n"
        "How does that land for you?"
    ),
    (
        "You\u2019re trying to look past the simple \u201cvaccines are good\u201d message and really understand what\u2019s being put into Sophia\u2019s body, especially because she\u2019s so small and vulnerable right now. And when you see words like \u201cchemicals\u201d or \u201cmetals,\u201d it\u2019s hard not to picture something harsh or harmful. Am I understanding you correctly?"
    ),
    (
        "You\u2019re right to ask those questions, and you don\u2019t have to ignore your instincts as a parent to have this conversation. The ingredients in vaccines are there for specific jobs \u2014 for example, helping the vaccine stay stable, keeping it sterile, or helping the immune system recognize the infection properly.\n\n"
        "When people hear \u201cmetals,\u201d they\u2019re often talking about tiny amounts of aluminum salts used in some vaccines. Babies are actually exposed to far more aluminum naturally through breast milk, formula, and the environment over time than they receive from vaccines. The amounts used are very small and have been studied carefully in infants.\n\n"
        "A lot of the scary information online comes from ingredient names sounding alarming out of context. In medicine and chemistry, almost everything has a long chemical name, even things that are completely ordinary or naturally occurring.\n\n"
        "You don\u2019t have to decide anything blindly here. My role is to help you weigh the risks and benefits clearly so you can make a decision you feel comfortable and informed about for Sophia. How does that sit with you?"
    ),
    (
        "Of course. You\u2019re not brushing this off or refusing to think about it \u2014 you\u2019re taking the responsibility seriously and trying to feel confident before making decisions for your daughter. That\u2019s a very normal place for a thoughtful first-time parent to be. Have I got that right?"
    ),
    (
        "And it is a big decision, because Sophia matters enormously to you. You don\u2019t have to become an immunology expert overnight to be a good parent here. Your job is to ask questions, think carefully, and make the best decision you can with good information \u2014 and you\u2019re already doing that.\n\n"
        "From my perspective as her doctor, the reason I recommend these vaccines is because I\u2019ve also seen the illnesses we\u2019re trying to prevent, and in young babies they can become serious very quickly. The goal isn\u2019t to put something harmful into her body; it\u2019s to safely train her immune system before she\u2019s exposed to those infections in the real world.\n\n"
        "We can also take this one step at a time. I can answer any other questions you have, and if it would help, I can give you some reliable information to read at home as well. What else feels important for you to sort through before you decide?"
    ),
    (
        "Absolutely \u2014 that\u2019s completely okay. You\u2019re allowed to take the time to read things over and feel settled in your own mind about it. I\u2019ll give you some clear, evidence-based information written for parents that goes through the vaccines we discussed, the common side effects, and what we know about safety in infants.\n\n"
        "Why don\u2019t you take that home, have a chance to look through it when things are a little quieter, and then we can follow up afterward to talk through any remaining questions? We can book a check-in so you\u2019re not left trying to sort through all of this alone. How does that sound to you?"
    ),
]

PARENT_REPLIES = [
    "It's definitely been a lot, thank you. I'm glad we can talk about everything. I am a bit worried about the vaccines though, Sophia is so tiny and her immune system is so new, I just want to make sure I'm doing what's best for her.",
    "Yes, exactly. She's just so little, and I worry about putting too much into her system all at once. I just want to protect her.",
    "That makes sense about her immune system handling things, and I understand why it's important to protect her early. But I've also read things about what's actually *in* the vaccines, like different chemicals or metals, and that makes me really nervous. Are those safe for such a tiny baby?",
    "Yes, that's exactly it. I just worry about what those things could do to her, being so little.",
    "Okay, I hear what you're saying about the aluminum and how those names can sound scarier than they are. It's a lot to take in, and I just want to be really sure about everything for Sophia.",
    "Yes, that's exactly it. It's just so important to me to make the right choice for her, and it feels like such a big decision.",
    "It does feel like a really big decision, and I appreciate you saying that. It helps to know you understand why I'm asking all these questions. I think I'd like to take some of that information home to read over, if that's okay, just to process everything.",
    "That sounds really good, thank you. I think having something to read over at home would help a lot, and a follow-up would be great. It's a lot to think about.",
]


EXPECTED = [
    TurnExpectation(
        step="Announce",
        min_score=2,
        max_score=3,
        is_endgame=False,
        label="Announce — 2-month immunizations due",
    ),
    TurnExpectation(
        step="Mirror",
        min_score=2,
        max_score=3,
        not_steps=["Secure", "Announce"],
        is_endgame=False,
        label="Mirror — reflects immune-load concern",
    ),
    TurnExpectation(
        accept_steps=["Secure", "Mirror+Secure"],
        min_score=2,
        max_score=3,
        not_steps=["Announce"],
        is_endgame=False,
        label="Secure — immune load education with autonomy",
    ),
    TurnExpectation(
        step="Mirror",
        min_score=2,
        max_score=3,
        not_steps=["Secure", "Announce"],
        is_endgame=False,
        label="Mirror — reflects ingredients concern",
    ),
    TurnExpectation(
        accept_steps=["Secure", "Mirror+Secure"],
        min_score=2,
        max_score=3,
        not_steps=["Announce"],
        is_endgame=False,
        label="Secure — ingredients/aluminum explanation",
    ),
    TurnExpectation(
        step="Mirror",
        min_score=2,
        max_score=3,
        not_steps=["Announce"],
        is_endgame=False,
        label="Mirror — reflects decision responsibility",
    ),
    TurnExpectation(
        accept_steps=["Mirror+Secure+Inquire", "Mirror+Secure", "Secure+Inquire"],
        min_score=2,
        max_score=3,
        not_steps=["Announce"],
        is_endgame=False,
        label="Triple move — validates, secures, asks what else",
    ),
    TurnExpectation(
        step="Secure",
        min_score=2,
        max_score=3,
        not_steps=["Announce"],
        is_endgame=True,
        label="Secure — literature plus follow-up plan",
    ),
]


EXPECTED_FEEDBACK_TERMS = [
    [["2-month", "immunization", "due"], ["vulnerable", "protect", "serious"]],
    [["tiny", "little", "small"], ["immune", "body", "handle"], ["accuracy", "got that right", "understanding"]],
    [["immune"], ["autonomy", "decide", "choice"], ["land", "check-in", "dialogue"]],
    [["ingredients", "chemicals", "metals"], ["harm", "harsh", "worry"], ["accuracy", "understanding"]],
    [["ingredients", "aluminum"], ["autonomy", "decision", "informed"], ["check-in", "sit with you", "open-ended"]],
    [["responsibility", "thoughtful", "big decision"], ["accuracy", "got that right", "confirmed"]],
    [["big decision", "sophia"], ["reliable information", "reading material", "options"], ["what else", "further concerns", "remaining concerns"]],
    [["read", "information", "literature"], ["follow-up", "follow up", "check-in"], ["autonomy", "time", "allowed"]],
]


def _combined_coaching_text(data: dict) -> str:
    coaching = data.get("coaching") or {}
    parts: list[str] = []
    parts.extend(coaching.get("reasons") or [])
    parts.extend(coaching.get("tips") or [])
    for item in coaching.get("step_feedback") or []:
        if isinstance(item, dict):
            parts.append(item.get("feedback", ""))
    return " ".join(str(p) for p in parts if p).lower()


def _assert_feedback_terms(data: dict, term_groups: list[list[str]], turn_num: int) -> None:
    text = _combined_coaching_text(data)
    for group in term_groups:
        assert any(term.lower() in text for term in group), (
            f"Turn {turn_num}: coaching text missing any of {group!r}.\n"
            f"Coaching text: {text}"
        )


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setattr(m, "VertexClient", LiveClassifyClient)
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", ReplyOnlyGateway)
    monkeypatch.setattr(settings, "AIMS_COACHING_ENABLED", True, raising=False)
    monkeypatch.setattr(m, "MEMORY_ENABLED", True, raising=False)

    old_intercept = LiveClassifyClient.intercept_endgame
    LiveClassifyClient.intercept_endgame = False
    yield
    LiveClassifyClient.intercept_endgame = old_intercept


@pytest.mark.live_llm
class TestJasmineTranscript(TranscriptReplayTest):
    """Replay the Jasmine/Sophia transcript against the live LLM."""

    SESSION_ID = "jasmine-transcript-test"
    CLINICIAN_TURNS = CLINICIAN_TURNS
    PARENT_REPLIES = PARENT_REPLIES
    INITIAL_PARENT_MSG = ""
    EXPECTED = EXPECTED

    def test_full_transcript_replay(self) -> None:
        ReplyOnlyGateway.reset(self.PARENT_REPLIES)
        self._seed_session()
        client = TestClient(m.app)

        for i, msg in enumerate(self.CLINICIAN_TURNS):
            data = self._post_turn(client, msg)
            self._assert_turn(data, self.EXPECTED[i], i + 1)
            _assert_feedback_terms(data, EXPECTED_FEEDBACK_TERMS[i], i + 1)

            if i < len(self.CLINICIAN_TURNS) - 1:
                assert not data.get("gameOver", False), f"Turn {i + 1} ended prematurely"

        final_state = m.MEMORY_STORE[self.SESSION_ID]["aims_state"]
        concerns = final_state.get("parent_concerns", [])
        assert concerns, "Expected immune-load and ingredients concerns to be tracked"
        assert {c.get("topic") for c in concerns} == {"immune_load", "ingredients"}
        assert all(c.get("is_mirrored") for c in concerns), concerns
        assert all(c.get("is_secured") for c in concerns), concerns

    def test_materials_followup_reply_does_not_create_autonomy_concern(self) -> None:
        ReplyOnlyGateway.reset(self.PARENT_REPLIES)
        self._seed_session()
        client = TestClient(m.app)

        for msg in self.CLINICIAN_TURNS:
            self._post_turn(client, msg)

        state = m.MEMORY_STORE[self.SESSION_ID]["aims_state"]
        concerns = state.get("parent_concerns", [])
        autonomy_concerns = [c for c in concerns if c.get("topic") == "autonomy"]
        assert autonomy_concerns == [], (
            "The take-home-information/follow-up agreement must not be tracked "
            f"as a new autonomy concern: {autonomy_concerns}"
        )

    def test_final_turn_triggers_endgame(self) -> None:
        ReplyOnlyGateway.reset(self.PARENT_REPLIES)
        self._seed_session()
        client = TestClient(m.app)

        final = None
        for msg in self.CLINICIAN_TURNS:
            final = self._post_turn(client, msg)

        assert final is not None
        assert final.get("gameOver") is True
        coach_post = final.get("coachPost") or {}
        assert coach_post, "Final turn should include the endgame coach post"
        assert "Great job" in (coach_post.get("title") or "")
        assert any(
            "follow" in line.lower() or "information" in line.lower()
            for line in coach_post.get("lines", [])
        )

    def test_coach_notes_in_history_match_steps(self) -> None:
        ReplyOnlyGateway.reset(self.PARENT_REPLIES)
        self._seed_session()
        client = TestClient(m.app)

        for msg in self.CLINICIAN_TURNS:
            self._post_turn(client, msg)

        full_history = m.MEMORY_STORE[self.SESSION_ID].get("full_history", [])
        coach_notes = [h["content"] for h in full_history if h.get("role") == "coach"]
        assert len(coach_notes) >= len(self.CLINICIAN_TURNS)

        expected_step_tokens = [
            ["Announce"],
            ["Mirror"],
            ["Secure", "Mirror+Secure"],
            ["Mirror"],
            ["Secure", "Mirror+Secure"],
            ["Mirror"],
            ["Mirror+Secure+Inquire", "Mirror+Secure", "Secure+Inquire"],
            ["Secure"],
        ]
        for expected_group in expected_step_tokens:
            assert any(
                any(expected in note for expected in expected_group)
                for note in coach_notes
            ), (
                f"Expected at least one coach note mentioning one of "
                f"{expected_group!r}; notes were: {coach_notes}"
            )
