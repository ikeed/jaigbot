"""
Focused /chat live-LLM state and endgame boundary tests.

Use these only where route-level state mutation matters. Prompt-only behavior
belongs in test_live_prompt_borderlines.py.
"""
from __future__ import annotations

import copy
import time

import pytest
from fastapi.testclient import TestClient

import app.main as m
from app.config import settings
from base import LiveClassifyClient, ReplyOnlyGateway


def _seed_session(*, session_id: str, initial_person_msg: str, aims_state: dict) -> None:
    m.MEMORY_STORE.pop(session_id, None)
    now = time.time()
    history = []
    full_history = []
    if initial_person_msg:
        entry = {"role": "assistant", "content": initial_person_msg}
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


def _secure_state_with_resolved_trust() -> dict:
    return {
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
    }


@pytest.fixture(autouse=True)
def setup_live_route_env(monkeypatch):
    monkeypatch.setattr(m, "VertexClient", LiveClassifyClient)
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", ReplyOnlyGateway)
    monkeypatch.setattr(
        "app.services.chat_orchestrator.storage_service.upload_session",
        lambda *args, **kwargs: False,
    )
    monkeypatch.setattr(settings, "AIMS_COACHING_ENABLED", True, raising=False)
    monkeypatch.setattr(m, "MEMORY_ENABLED", True, raising=False)

    old_intercept = LiveClassifyClient.intercept_endgame
    LiveClassifyClient.intercept_endgame = False
    yield
    LiveClassifyClient.intercept_endgame = old_intercept


@pytest.mark.live_llm
def test_live_route_materials_followup_acceptance_does_not_create_new_unmirrored_concern():
    session_id = "live-route-materials-followup"
    ReplyOnlyGateway.reset([
        "That sounds good. I'll read it at home, and we can talk again at the next visit."
    ])
    _seed_session(
        session_id=session_id,
        initial_person_msg=(
            "I think I'd like to read information at home and follow up later, if that's okay."
        ),
        aims_state=_secure_state_with_resolved_trust(),
    )

    client = TestClient(m.app)
    data = _post_turn(
        client,
        session_id=session_id,
        message=(
            "Absolutely. I'll send clear information home and book a follow-up "
            "so we can go through any remaining questions."
        ),
    )

    assert data.get("gameOver", False)
    assert "coachPost" in data
    concerns = m.MEMORY_STORE[session_id]["aims_state"].get("parent_concerns", [])
    assert [c for c in concerns if c.get("topic") == "autonomy"] == []
    assert all(c.get("is_mirrored") for c in concerns), concerns


@pytest.mark.live_llm
def test_live_route_literature_only_near_miss_does_not_end():
    session_id = "live-route-literature-only"
    ReplyOnlyGateway.reset([
        "I'd like something to read at home, but I'm not ready to plan another visit about vaccines."
    ])
    _seed_session(
        session_id=session_id,
        initial_person_msg="I need time to think and would like something to read at home.",
        aims_state=_secure_state_with_resolved_trust(),
    )

    client = TestClient(m.app)
    data = _post_turn(
        client,
        session_id=session_id,
        message="I can send information home and we can follow up if that would help.",
    )

    assert not data.get("gameOver", False)
    assert "coachPost" not in data


@pytest.mark.live_llm
def test_live_route_compound_turn_resolves_final_concern_then_acceptance_can_end():
    session_id = "live-route-compound-resolves"
    ReplyOnlyGateway.reset(["That answers my question. I'm comfortable proceeding with the vaccine today."])
    _seed_session(
        session_id=session_id,
        initial_person_msg="I'm worried about serious side effects.",
        aims_state={
            "announced": True,
            "phase": "InquireMirror",
            "first_inquire_done": True,
            "pending_concerns": True,
            "parent_concerns": [
                {
                    "id": "side-effects",
                    "topic": "side_effects",
                    "summary": "wants side effect risk addressed",
                    "desc": "wants side effect risk addressed",
                    "is_mirrored": False,
                    "is_secured": False,
                    "status": "open",
                }
            ],
        },
    )

    client = TestClient(m.app)
    data = _post_turn(
        client,
        session_id=session_id,
        message=(
            "You're worried about serious side effects, and you want to know this is safe. "
            "Serious reactions are very rare and safety is monitored closely. "
            "What else would help you feel ready?"
        ),
    )

    concern = m.MEMORY_STORE[session_id]["aims_state"]["parent_concerns"][0]
    assert concern["is_mirrored"] is True
    assert concern["is_secured"] is True
    assert data.get("gameOver", False)
    assert "coachPost" in data


@pytest.mark.live_llm
def test_live_route_negative_literature_reply_blocks_endgame_with_active_trust_concern():
    session_id = "live-route-negative-literature"
    ReplyOnlyGateway.reset(["I'm not going to read that information, and I still don't trust this."])
    _seed_session(
        session_id=session_id,
        initial_person_msg="I still don't trust whether the evidence is being presented honestly.",
        aims_state={
            "announced": True,
            "phase": "Secure",
            "first_inquire_done": True,
            "pending_concerns": True,
            "parent_concerns": [],
        },
    )

    client = TestClient(m.app)
    data = _post_turn(
        client,
        session_id=session_id,
        message="I can send written information home and arrange a follow-up visit.",
    )

    concerns = m.MEMORY_STORE[session_id]["aims_state"].get("parent_concerns", [])
    assert any(c.get("topic") == "trust" for c in concerns), concerns
    assert not data.get("gameOver", False)
    assert "coachPost" not in data
