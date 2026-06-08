"""
Live-LLM borderline calibration tests.

These are intentionally narrow, transcript-style checks aimed at the prompt
and endgame decision boundaries that are hardest to validate with mocks:
- late-stage closing offers should classify as Secure rather than plain Inquire
- polite appreciation without a return plan should not end the session
- analytical residual uncertainty plus literature/follow-up should resolve
- mixed resolution (one vaccine today, literature on others) should resolve
"""
from __future__ import annotations

import copy
import time

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.config import settings
from base import LiveClassifyClient, ReplyOnlyGateway


def _seed_session(*, session_id: str, initial_parent_msg: str, aims_state: dict) -> None:
    now = time.time()
    history = []
    full_history = []
    if initial_parent_msg:
        entry = {"role": "assistant", "content": initial_parent_msg}
        history.append(entry)
        full_history.append({**entry, "time": now})

    m.MEMORY_STORE[session_id] = {
        "history": history,
        "full_history": full_history,
        "character": None,
        "scene": None,
        "updated": now,
        "session_started": now,
        "aims_state": copy.deepcopy(aims_state),
        "aims": {
            "perStepCounts": {
                "Announce": 1,
                "Inquire": 1,
                "Mirror": 1,
                "Secure": 1,
                "Announce+Inquire": 0,
                "Mirror+Inquire": 0,
                "Mirror+Secure": 0,
                "Secure+Inquire": 0,
            },
            "scores": {
                "Announce": [2],
                "Inquire": [2],
                "Mirror": [2],
                "Secure": [2],
                "Announce+Inquire": [],
                "Mirror+Inquire": [],
                "Mirror+Secure": [],
                "Secure+Inquire": [],
            },
            "totalTurns": 4,
        },
    }


def _post_turn(client: TestClient, *, session_id: str, message: str) -> dict:
    response = client.post(
        "/chat",
        json={"message": message, "coach": True, "sessionId": session_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


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
def test_live_closing_offer_classifies_as_secure_not_inquire():
    session_id = "live-borderline-secure"
    ReplyOnlyGateway.reset(["That sounds okay, thank you."])
    _seed_session(
        session_id=session_id,
        initial_parent_msg="I think I'd like something to read at home, if that's okay, just to process everything.",
        aims_state={
            "announced": True,
            "phase": "Secure",
            "first_inquire_done": True,
            "pending_concerns": False,
            "parent_concerns": [
                {
                    "id": "trust",
                    "topic": "trust",
                    "summary": "wants evidence, uncertainty, and trust addressed",
                    "desc": "wants evidence, uncertainty, and trust addressed",
                    "is_mirrored": True,
                    "is_secured": True,
                    "status": "resolved",
                }
            ],
        },
    )
    client = TestClient(m.app)
    data = _post_turn(
        client,
        session_id=session_id,
        message=(
            "Absolutely. I'll give you some clear, evidence-based information to take home, and we can "
            "book a follow-up so you're not left sorting through all of this alone. How does that sound?"
        ),
    )
    step = data.get("coaching", {}).get("step")
    assert step and "Secure" in step
    assert step != "Inquire"


@pytest.mark.live_llm
def test_live_polite_appreciation_near_miss_does_not_end():
    session_id = "live-near-miss"
    ReplyOnlyGateway.reset(["That sounds fair, thank you. I appreciate you not pushing."])
    _seed_session(
        session_id=session_id,
        initial_parent_msg="I still need to think this over a bit.",
        aims_state={
            "announced": True,
            "phase": "Secure",
            "first_inquire_done": True,
            "pending_concerns": False,
            "parent_concerns": [
                {
                    "id": "trust",
                    "topic": "trust",
                    "summary": "wants evidence, uncertainty, and trust addressed",
                    "desc": "wants evidence, uncertainty, and trust addressed",
                    "is_mirrored": True,
                    "is_secured": True,
                    "status": "resolved",
                }
            ],
        },
    )
    client = TestClient(m.app)
    data = _post_turn(
        client,
        session_id=session_id,
        message="I can send you home with something to read if that would help.",
    )
    assert not data.get("gameOver", False)
    assert "coachPost" not in data


@pytest.mark.live_llm
def test_live_analytical_residual_uncertainty_plus_followup_can_end():
    session_id = "live-accepted-literature"
    ReplyOnlyGateway.reset(
        ["I'm still weighing the numbers, but I have enough to review at home, and we can talk about it again at the next appointment."]
    )
    _seed_session(
        session_id=session_id,
        initial_parent_msg="I want to understand the uncertainty in the evidence before I decide.",
        aims_state={
            "announced": True,
            "phase": "Secure",
            "first_inquire_done": True,
            "pending_concerns": False,
            "parent_concerns": [
                {
                    "id": "trust",
                    "topic": "trust",
                    "summary": "wants evidence, uncertainty, and trust addressed",
                    "desc": "wants evidence, uncertainty, and trust addressed",
                    "is_mirrored": True,
                    "is_secured": True,
                    "status": "resolved",
                }
            ],
        },
    )
    client = TestClient(m.app)
    data = _post_turn(
        client,
        session_id=session_id,
        message=(
            "I can send you home with the evidence summary and we can revisit this in two weeks, after "
            "you've had a chance to look through it."
        ),
    )
    assert data.get("gameOver", False)
    concerns = m.MEMORY_STORE[session_id]["aims_state"].get("parent_concerns", [])
    assert all(c.get("topic") != "autonomy" for c in concerns)


@pytest.mark.live_llm
def test_live_mixed_resolution_one_vaccine_today_and_literature_for_others_ends():
    session_id = "live-mixed-resolution"
    ReplyOnlyGateway.reset(
        ["That sounds like a reasonable plan. I'm comfortable proceeding with the Tdap today, and I'd appreciate reading material for the others."]
    )
    _seed_session(
        session_id=session_id,
        initial_parent_msg="I want to be thoughtful about the recommendation.",
        aims_state={
            "announced": True,
            "phase": "Secure",
            "first_inquire_done": True,
            "pending_concerns": False,
            "parent_concerns": [
                {
                    "id": "trust",
                    "topic": "trust",
                    "summary": "wants evidence, uncertainty, and trust addressed",
                    "desc": "wants evidence, uncertainty, and trust addressed",
                    "is_mirrored": True,
                    "is_secured": True,
                    "status": "resolved",
                }
            ],
        },
    )
    client = TestClient(m.app)
    data = _post_turn(
        client,
        session_id=session_id,
        message="We could do the Tdap today and send you home with information on the others.",
    )
    assert data.get("gameOver", False)
    assert "coachPost" in data
