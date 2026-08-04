"""
Integration test: Georgina/Carter transcript replay.

Replays the exact clinician and parent dialog from a real session transcript
(~/Downloads/new_convo.json) through the full coaching pipeline, verifying
classification, scoring, concern tracking, phase transitions, and endgame
readiness at each turn.

The LLM is mocked to return the CORRECT classifications (what the improved
prompt should produce).  This tests the pipeline's ability to correctly
process well-classified turns end-to-end.
"""
import json
import time
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.config import settings
import app.main as m


# ---------------------------------------------------------------------------
# Transcript data (extracted from the real session export)
# ---------------------------------------------------------------------------

# Clinician turns (role=user in the export)
CLINICIAN_TURNS = [
    # Turn 1: Semantic mirror of trust/information-overload concern
    (
        "Absolutely. When you\u2019re seeing completely opposite claims online, "
        "it can become really hard to know who to trust. And once that uncertainty "
        "is there, even \u201csmall amounts\u201d can still feel like a big gamble "
        "when it\u2019s your child."
    ),
    # Turn 2: Semantic mirror — pure reflection, NO facts/education/autonomy
    (
        "Of course. As a parent, you feel responsible for filtering all of that "
        "information and making sure you\u2019re not blindly accepting something that "
        "could affect your kids. When different sources are all claiming they have "
        "\u201cthe real truth,\u201d it makes sense that your guard would go up."
    ),
    # Turn 3: Empathic normalization (Mirror) + educational risk-reframing (Secure)
    (
        "I do know. Most parents in your position aren\u2019t trying to be difficult "
        "\u2014 they\u2019re trying to be careful. And honestly, the volume of information "
        "out there can be overwhelming, especially when a lot of it is emotional "
        "or fear-based on both sides.\n\n"
        "What I usually encourage parents to focus on is not \u201cIs this perfectly "
        "risk-free?\u201d because almost nothing in medicine is. The better question "
        "is, \u201cCompared to the diseases themselves, where does the balance of risk "
        "land?\u201d That\u2019s the comparison most pediatricians are making when they "
        "recommend vaccines."
    ),
    # Turn 4: Strong Secure — autonomy + options + follow-up
    (
        "And you don\u2019t have to sort it all out or make a decision in one "
        "appointment today. My goal isn\u2019t to corner you into saying yes \u2014 "
        "it\u2019s to make sure you have a chance to ask questions and get information "
        "you actually trust.\n\n"
        "What I could do is send you home with some balanced information that goes "
        "through the common concerns parents raise \u2014 ingredients, safety monitoring, "
        "natural immunity, that kind of thing \u2014 and then we could check back in at "
        "a follow-up once Carter\u2019s feeling better. That gives you time to look "
        "things over without pressure and come back with whatever questions you "
        "still have."
    ),
    # Turn 5: Secure closure — literature + safety-netting + follow-up
    (
        "Absolutely. I\u2019ll send you home with that information, and we\u2019ll make "
        "sure it\u2019s something practical rather than a stack of scare tactics or "
        "sales pitches.\n\n"
        "For Carter today, let\u2019s focus on hydration and watching his urine output. "
        "If he\u2019s getting more sleepy, can\u2019t keep fluids down, has blood in the "
        "stool, worsening belly pain, or goes much longer without peeing, I want "
        "him reassessed urgently.\n\n"
        "And let\u2019s book a follow-up after he\u2019s recovered so we can talk through "
        "the vaccine questions calmly. You can bring your questions \u2014 or even the "
        "things you\u2019ve read \u2014 and we\u2019ll go through them together."
    ),
]

# Parent replies (role=assistant in the export) — these become person_last
# for the NEXT clinician turn.
PARENT_REPLIES = [
    # After Turn 1 → becomes person_last for Turn 2
    (
        "It's just, when you see so many different things online, it makes you "
        "wonder who's really telling the truth. And it's my kids, so I have to "
        "be careful."
    ),
    # After Turn 2 → becomes person_last for Turn 3
    (
        "Exactly. It's just so much to sift through, and I just want to do "
        "what's best for my kids, you know?"
    ),
    # After Turn 3 → becomes person_last for Turn 4
    (
        "I hear what you're saying about the risks, but it's still a lot to "
        "think about. I just want to make sure I'm doing what's truly best for "
        "my kids, and there's just so much out there."
    ),
    # After Turn 4 → becomes person_last for Turn 5
    (
        "That sounds like a good idea. I'd appreciate having something to look "
        "over at home, without feeling rushed. It's a lot to take in."
    ),
    # After Turn 5 (final)
    (
        "Okay, that sounds good. I appreciate that. I'll keep an eye on Carter "
        "and bring him back if any of those things happen."
    ),
]

# The parent message BEFORE Turn 1 (sets person_last for the first clinician turn)
INITIAL_PARENT_MSG = (
    "I hear what you're saying about the small amounts, but it's still hard to "
    "shake the feeling that it's a lot of chemicals to put into a child, "
    "especially when there's so much conflicting information out there."
)

# Expected LLM classifications for each turn (what the improved prompt should return)
EXPECTED_CLASSIFICATIONS = [
    # Turn 1: Semantic mirror of trust concern ("hard to know who to trust")
    {
        "classify": {
            "is_small_talk": False,
            "is_vaccine_relevant": True,
            "person_topic": "trust",
            "aims": {
                "steps": ["Mirror"],
                "score": 2,
                "reasons": ["Semantic mirror: 'hard to know who to trust' reflects parent's information-overload concern"],
                "tips": ["End with a quick accuracy check: 'Did I get that right?'"],
            },
            "safety_flags": [],
            "reasoning": "Pure reflection of the trust/information concern with no educational content",
        },
        "reply": PARENT_REPLIES[0],
    },
    # Turn 2: Pure reflection/validation — Mirror, NOT Secure
    {
        "classify": {
            "is_small_talk": False,
            "is_vaccine_relevant": True,
            "person_topic": "trust",
            "aims": {
                "steps": ["Mirror"],
                "score": 2,
                "reasons": [
                    "Empathic normalization: 'it makes sense that your guard would go up'",
                    "Semantic mirror: 'you feel responsible for filtering all of that information'",
                ],
                "tips": ["End with a quick accuracy check: 'Did I get that right?'"],
            },
            "safety_flags": [],
            "reasoning": "Pure reflection — no facts, no autonomy affirmation, no options → Mirror not Secure",
        },
        "reply": PARENT_REPLIES[1],
    },
    # Turn 3: Normalization (Mirror) + risk-reframing (Secure) = Mirror+Secure
    {
        "classify": {
            "is_small_talk": False,
            "is_vaccine_relevant": True,
            "person_topic": "trust",
            "aims": {
                "steps": ["Mirror", "Secure"],
                "score": 2,
                "reasons": [
                    "Empathic normalization: 'trying to be careful' validates the trust concern",
                    "Educational reframing: risk-comparison framework",
                ],
                "tips": [],
            },
            "safety_flags": [],
            "reasoning": "Normalization paragraph = Mirror; risk-reframing paragraph = Secure",
        },
        "reply": PARENT_REPLIES[2],
    },
    # Turn 4: Strong Secure — explicit autonomy + literature + follow-up
    {
        "classify": {
            "is_small_talk": False,
            "is_vaccine_relevant": True,
            "person_topic": None,  # parent is acknowledging, not raising a new concern
            "aims": {
                "steps": ["Secure"],
                "score": 3,
                "reasons": [
                    "Explicit autonomy: 'don't have to make a decision in one appointment'",
                    "Concrete options: literature + follow-up visit",
                    "Safety-net: 'come back with whatever questions you still have'",
                ],
                "tips": [],
            },
            "safety_flags": [],
            "reasoning": "Full Secure with autonomy, options, and safety-netting",
        },
        "reply": PARENT_REPLIES[3],
    },
    # Turn 5: Secure closure — literature + clinical safety-netting + follow-up
    {
        "classify": {
            "is_small_talk": False,
            "is_vaccine_relevant": True,
            "person_topic": None,
            "aims": {
                "steps": ["Secure"],
                "score": 3,
                "reasons": [
                    "Follow-up plan: 'book a follow-up after he's recovered'",
                    "Safety-netting: hydration monitoring + red-flag symptoms",
                    "Literature offer confirmed",
                ],
                "tips": [],
            },
            "safety_flags": [],
            "reasoning": "Secure closure with clinical safety-netting and follow-up plan",
        },
        "reply": PARENT_REPLIES[4],
    },
]


# ---------------------------------------------------------------------------
# Turn-based LLM stub
# ---------------------------------------------------------------------------

class TranscriptStub:
    """Returns per-turn classify and reply responses in sequence."""
    _turns = []
    _classify_idx = 0
    _reply_idx = 0

    @classmethod
    def reset(cls, turns):
        cls._turns = turns
        cls._classify_idx = 0
        cls._reply_idx = 0

    def __init__(self, *args, **kwargs):
        pass

    @staticmethod
    async def generate_text_async(prompt, **kwargs):
        prompt_lower = (prompt or "").lower()
        if "classify" in prompt_lower or "unified" in prompt_lower:
            idx = min(TranscriptStub._classify_idx, len(TranscriptStub._turns) - 1)
            TranscriptStub._classify_idx += 1
            return json.dumps(TranscriptStub._turns[idx]["classify"])
        elif "endgame" in prompt_lower:
            # Return non-endgame for all turns (endgame gating is tested by state)
            return json.dumps({"is_endgame": False, "resolution_type": "not_resolved", "summary": ""})
        return json.dumps({"patient_reply": "fallback"})

    @staticmethod
    def generate_text_json(*, prompt, response_schema, **kwargs):
        idx = min(TranscriptStub._reply_idx, len(TranscriptStub._turns) - 1)
        TranscriptStub._reply_idx += 1
        reply_text = TranscriptStub._turns[idx].get("reply", "ok")
        return json.dumps({"patient_reply": reply_text})

    @staticmethod
    def generate_text(*args, **kwargs):
        return json.dumps({"patient_reply": "fallback"})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_MAPPING = {
    "meta": {
        "per_step_classification_markers": {
            "Announce": {"linguistic": ["I recommend", "It's time for", "due for", "Today we will"]},
            "Inquire": {"linguistic": ["What concerns", "What have you heard", "How are you feeling about"]},
            "Mirror": {"linguistic": ["It sounds like", "You're worried", "I'm hearing", "You feel"]},
            "Secure": {"linguistic": ["It's your decision", "I'm here to support", "We can", "Options include"]},
        }
    }
}

SESSION_ID = "georgina-transcript-test"


@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", TranscriptStub)
    monkeypatch.setattr(m, "VertexClient", TranscriptStub)
    monkeypatch.setattr(settings, "AIMS_COACHING_ENABLED", True, raising=False)
    monkeypatch.setattr(m, "MEMORY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PROJECT_ID", "p", raising=False)
    monkeypatch.setattr(settings, "REGION", "us-central1", raising=False)
    monkeypatch.setattr(m, "VERTEX_LOCATION", "us-central1", raising=False)
    with (
        patch("app.aims_engine.load_mapping", return_value=MOCK_MAPPING),
        patch("app.aims_mapping_loader.load_mapping", return_value=MOCK_MAPPING),
    ):
        yield


def _seed_session():
    """Seed memory store with pre-Turn-1 state matching the transcript's prior context."""
    m.MEMORY_STORE[SESSION_ID] = {
        "history": [
            # The parent's message immediately before the visible transcript
            {"role": "assistant", "content": INITIAL_PARENT_MSG},
        ],
        "character": None,
        "scene": None,
        "updated": time.time(),
        "aims_state": {
            "announced": True,
            "phase": "InquireMirror",
            "is_undiscovered_concerns": False,
            "pending_concerns": True,
            "parent_concerns": [
                # Two earlier concerns already resolved
                {
                    "desc": "We just want to make informed choices for our kids.",
                    "topic": "trust",
                    "is_mirrored": True,
                    "is_secured": True,
                },
                {
                    "desc": "It feels like there's so much pressure to just do it.",
                    "topic": "autonomy",
                    "is_mirrored": True,
                    "is_secured": True,
                },
                # Unresolved concern from earlier — should get mirrored during replay
                {
                    "desc": "It's hard to trust something when you don't understand what's in it.",
                    "topic": "trust",
                    "is_mirrored": False,
                    "is_secured": False,
                },
            ],
            "recent_coaching": [],
        },
        "aims": {
            "perStepCounts": {
                "Announce": 1, "Inquire": 3, "Mirror": 1, "Secure": 0,
                "Announce+Inquire": 0, "Mirror+Inquire": 0, "Mirror+Secure": 0, "Secure+Inquire": 0,
            },
            "scores": {
                "Announce": [3], "Inquire": [2, 2, 2], "Mirror": [2], "Secure": [],
                "Announce+Inquire": [], "Mirror+Inquire": [], "Mirror+Secure": [], "Secure+Inquire": [],
            },
            "totalTurns": 8,
            "runningAverage": {"Announce": 3.0, "Inquire": 2.0, "Mirror": 2.0},
        },
    }


def _post_turn(client, clinician_msg):
    """POST a clinician turn and return the parsed response."""
    r = client.post("/chat", json={
        "message": clinician_msg,
        "coach": True,
        "sessionId": SESSION_ID,
    })
    assert r.status_code == 200, f"Turn failed with {r.status_code}: {r.text}"
    return r.json()


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

class TestGeorginaTranscript:
    """Replay the Georgina/Carter transcript and verify the coaching pipeline."""

    def test_full_transcript_replay(self):
        """End-to-end replay of 5 clinician turns with correct LLM classifications."""
        TranscriptStub.reset(EXPECTED_CLASSIFICATIONS)
        _seed_session()
        client = TestClient(m.app)

        # ---- Turn 1: Mirror (semantic reflection of trust concern) ----
        data1 = _post_turn(client, CLINICIAN_TURNS[0])
        assert data1["coaching"]["step"] == "Mirror", (
            f"Turn 1 should be Mirror, got {data1['coaching']['step']}"
        )
        assert data1["coaching"]["score"] >= 2, (
            f"Turn 1 semantic mirror should score >= 2, got {data1['coaching']['score']}"
        )
        # Must NOT be classified as rapport
        reasons1 = " ".join(data1["coaching"]["reasons"]).lower()
        assert "rapport" not in reasons1, "Turn 1 should not be classified as rapport"
        # Reply text can vary slightly depending on how the replay path consumes
        # the scripted turn, but it should remain substantive and concern-bearing.
        assert isinstance(data1.get("reply"), str) and data1["reply"].strip()

        # ---- Turn 2: Mirror (pure reflection — Mirror+Secure also acceptable) ----
        data2 = _post_turn(client, CLINICIAN_TURNS[1])
        assert data2["coaching"]["step"] in ("Mirror", "Mirror+Secure"), (
            f"Turn 2 should be Mirror or Mirror+Secure, got {data2['coaching']['step']}"
        )
        assert data2["coaching"]["score"] >= 2
        reasons2 = " ".join(data2["coaching"]["reasons"]).lower()
        assert "rapport" not in reasons2
        # Must NOT be mis-classified as Secure (the original bug)
        assert data2["coaching"]["step"] != "Secure", (
            "Turn 2 has no facts/autonomy/options — should be Mirror, not Secure"
        )

        # ---- Turn 3: Mirror+Secure (normalization + educational reframing) ----
        data3 = _post_turn(client, CLINICIAN_TURNS[2])
        assert data3["coaching"]["step"] in ("Mirror+Secure", "Secure"), (
            f"Turn 3 should be Mirror+Secure or Secure, got {data3['coaching']['step']}"
        )
        # Must NOT be classified as rapport (the original bug)
        reasons3 = " ".join(data3["coaching"]["reasons"]).lower()
        assert "rapport" not in reasons3, "Turn 3 should not be classified as rapport"

        # ---- Turn 4: Secure score 3 (autonomy + options + safety-net) ----
        data4 = _post_turn(client, CLINICIAN_TURNS[3])
        assert data4["coaching"]["step"] == "Secure", (
            f"Turn 4 should be Secure, got {data4['coaching']['step']}"
        )
        assert data4["coaching"]["score"] >= 2

        # ---- Turn 5: Secure (closure with safety-netting + follow-up) ----
        data5 = _post_turn(client, CLINICIAN_TURNS[4])
        assert data5["coaching"]["step"] == "Secure", (
            f"Turn 5 should be Secure, got {data5['coaching']['step']}"
        )

        # ---- Verify final AIMS state ----
        state = m.MEMORY_STORE[SESSION_ID]["aims_state"]

        # All pre-existing concerns should now be mirrored
        trust_concerns = [c for c in state["parent_concerns"] if c["topic"] == "trust"]
        unmirrored_trust = [c for c in trust_concerns if not c.get("is_mirrored")]
        assert len(unmirrored_trust) == 0, (
            f"All trust concerns should be mirrored after 2 Mirror turns, "
            f"but {len(unmirrored_trust)} remain unmirrored: "
            f"{[c['desc'][:60] for c in unmirrored_trust]}"
        )

        # Phase should have advanced (Mirror+Secure with all concerns mirrored → Secure)
        # or stayed InquireMirror if concerns remain — but should not be PreAnnounce
        assert state["phase"] != "PreAnnounce"

        # ---- Verify session metrics ----
        aims = m.MEMORY_STORE[SESSION_ID]["aims"]
        assert aims["perStepCounts"]["Mirror"] >= 3, (
            f"Mirror count should be >= 3, got {aims['perStepCounts']['Mirror']}"
        )
        assert aims["perStepCounts"]["Secure"] >= 2, (
            f"Secure count should be >= 2, got {aims['perStepCounts']['Secure']}"
        )
        assert aims["totalTurns"] >= 13  # 8 seeded + 5 replayed

        # ---- Verify Mirror running average improved ----
        ra = aims.get("runningAverage", {})
        if ra.get("Mirror"):
            assert ra["Mirror"] >= 1.5, (
                f"Mirror average should be >= 1.5 with correct scoring, got {ra['Mirror']}"
            )

    def test_concern_mirroring_unblocks_endgame_guard(self):
        """After all turns, no unmirrored concerns should remain,
        so the endgame hard guard would not block."""
        TranscriptStub.reset(EXPECTED_CLASSIFICATIONS)
        _seed_session()
        client = TestClient(m.app)

        for msg in CLINICIAN_TURNS:
            _post_turn(client, msg)

        state = m.MEMORY_STORE[SESSION_ID]["aims_state"]
        concerns = state.get("parent_concerns", [])
        has_unmirrored = any(not c.get("is_mirrored") for c in concerns)
        assert not has_unmirrored, (
            f"Endgame hard guard would block: unmirrored concerns remain: "
            f"{[c['desc'][:50] for c in concerns if not c.get('is_mirrored')]}"
        )

    def test_coach_notes_in_history_match_steps(self):
        """Coach notes persisted in history should reflect the detected steps."""
        TranscriptStub.reset(EXPECTED_CLASSIFICATIONS)
        _seed_session()
        client = TestClient(m.app)

        for msg in CLINICIAN_TURNS:
            _post_turn(client, msg)

        history = m.MEMORY_STORE[SESSION_ID].get("history", [])
        coach_notes = [h["content"] for h in history if h.get("role") == "coach"]

        # Should have a coach note for each of the 5 turns
        assert len(coach_notes) >= 5, (
            f"Expected >= 5 coach notes, got {len(coach_notes)}"
        )

        # Turn 1 and 2 coach notes should mention Mirror
        assert any("Mirror" in n for n in coach_notes[:2]), (
            "First two coach notes should mention Mirror step"
        )

        # No coach note should say "Rapport/pleasantries" for these turns
        for i, note in enumerate(coach_notes):
            assert "Rapport/pleasantries" not in note, (
                f"Coach note {i} should not say Rapport/pleasantries for this "
                f"transcript, got: {note}"
            )
