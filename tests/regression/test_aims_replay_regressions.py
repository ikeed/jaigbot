from __future__ import annotations

import logging
import time
from unittest.mock import AsyncMock, Mock

import pytest

from app.constants import KEY_AIMS_STATE, KEY_COACH_POST, KEY_GAME_OVER, KEY_UPDATED, SESSION_HISTORY
from app.models import ChatRequest, ClassifierResult, Coaching
from app.services.aims_coaching_handler import AimsCoachingHandler
from app.services.aims_endgame_service import AimsEndgameService
from app.services.aims_turn_coordinator import AimsTurnResult
from app.services.chat_context import ChatContext


class _QueuedEndgameClassifier:
    def __init__(self, results: list[dict]):
        self._results = list(results)
        self.calls: list[dict] = []

    async def detect_endgame(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        if self._results:
            return self._results.pop(0)
        return {
            "is_endgame": False,
            "resolution_type": "not_resolved",
            "summary": "",
            "reason": "",
        }


def _turn(
    *,
    step: str | None,
    score: int | None,
    patient_reply: str,
    reasons: list[str] | None = None,
    tips: list[str] | None = None,
    person_topic: str | None = None,
    person_events: list[dict] | None = None,
) -> AimsTurnResult:
    coaching = Coaching(
        step=step,
        steps=[step] if step else [],
        score=score,
        reasons=reasons or [],
        tips=tips or [],
    )
    classification_result = ClassifierResult(
        is_small_talk=False,
        is_vaccine_relevant=True,
        aims=coaching,
        safety_flags=[],
        person_topic=person_topic,
        reasoning="test",
        person_events=person_events or [],
    )
    return AimsTurnResult(
        cls_payload=classification_result.aims.model_dump(),
        is_vaccine_relevant=True,
        is_small_talk=False,
        classification_result=classification_result,
        reply_payload={"patient_reply": patient_reply},
        was_fallback=False,
    )


def _metrics():
    metrics = Mock()
    metrics.persist.return_value = None
    metrics.build_summary.return_value = {
        "totalTurns": 1,
        "perStepCounts": {"Secure": 1},
        "runningAverage": {"Secure": 2.0},
    }
    return metrics


def _feedback():
    feedback = Mock()
    feedback.filter_user_facing_reasons.side_effect = lambda reasons, step=None: list(reasons or [])
    feedback.append.return_value = None
    return feedback


def _handler(*, turn_results: list[AimsTurnResult], endgame_results: list[dict]) -> tuple[AimsCoachingHandler, dict]:
    memory_store: dict = {}
    endgame_classifier = _QueuedEndgameClassifier(endgame_results)
    handler = AimsCoachingHandler(
        memory_store=memory_store,
        vertex_config={
            "project_id": "proj",
            "region": "us-central1",
            "vertex_location": "us-central1",
            "model_id": "model",
            "model_fallbacks": [],
            "temperature": 0.0,
            "max_tokens": 256,
            "client_cls": None,
        },
        memory_config={"enabled": True, "max_turns": 10},
        logger=logging.getLogger("test"),
        classifier_service=Mock(),
        patient_reply_service=Mock(),
        metrics_service=_metrics(),
        coach_feedback_history_service=_feedback(),
        endgame_service=AimsEndgameService(
            logger=logging.getLogger("test"),
            classifier_service_getter=lambda: endgame_classifier,
        ),
        turn_coordinator=Mock(),
    )
    handler.turn_coordinator.run = AsyncMock(side_effect=turn_results)
    return handler, memory_store


def _context(
    *,
    session_id: str,
    mem: dict,
    person_last: str,
    history_text: str = "",
    character: str = "Persona text",
) -> ChatContext:
    return ChatContext(
        session_id=session_id,
        generated_session=False,
        mem=mem,
        effective_character=character,
        effective_scene="Scene text",
        system_instruction=None,
        history_text=history_text,
        person_last=person_last,
        user_info={"identifier": "clinician@example.com", "metadata": {"name": "Craig Burnett"}},
    )


def _sync_ctx(ctx: ChatContext, memory_store: dict, result: dict) -> None:
    object.__setattr__(ctx, "mem", memory_store[ctx.session_id])
    object.__setattr__(ctx, "person_last", result["reply"])
    lines = []
    for item in ctx.mem.get(SESSION_HISTORY, []):
        role = item.get("role")
        speaker = "Doctor" if role == "user" else "Assistant"
        lines.append(f"{speaker}: {item.get('content')}")
    object.__setattr__(ctx, "history_text", "\n".join(lines))


def _resolved_trust_state() -> dict:
    return {
        "announced": True,
        "phase": "Secure",
        "is_undiscovered_concerns": False,
        "pending_concerns": False,
        "parent_concerns": [
            {
                "id": "trust",
                "topic": "trust",
                "summary": "wants evidence, uncertainty, and trust addressed",
                "desc": "wants evidence, uncertainty, and trust addressed",
                "evidence": ["I want to understand the data."],
                "is_mirrored": True,
                "is_secured": True,
                "status": "resolved",
                "mirror_count": 1,
                "secure_count": 1,
            }
        ],
        "recent_coaching": [],
    }


@pytest.mark.asyncio
async def test_replay_split_acceptance_requires_second_turn():
    handler, memory_store = _handler(
        turn_results=[
            _turn(
                step="Secure",
                score=2,
                patient_reply="Yes, some written information would be helpful for me to review at home.",
                reasons=["You supported autonomy and offered materials."],
                person_topic=None,
            ),
            _turn(
                step="Secure",
                score=2,
                patient_reply="A follow-up appointment in a few weeks sounds good.",
                reasons=["You gave a concrete review plan."],
                person_topic=None,
            ),
        ],
        endgame_results=[
            {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": "detection_error"},
            {
                "is_endgame": True,
                "resolution_type": "accepted_literature",
                "summary": "Person accepted written information and a follow-up.",
                "reason": "",
                "accepted_materials": True,
                "accepted_followup": True,
                "remaining_active_concern": False,
            },
        ],
    )
    session_id = "split-acceptance"
    mem = {
        SESSION_HISTORY: [],
        "full_history": [],
        KEY_AIMS_STATE: _resolved_trust_state(),
        KEY_UPDATED: time.time(),
    }
    ctx = _context(session_id=session_id, mem=mem, person_last="I need a little time to think it over.")

    result1 = await handler.handle(
        req=None,
        body=ChatRequest(message="I can send you home with the evidence summary.", sessionId=session_id, coach=True),
        ctx=ctx,
    )
    assert "coach_post" not in result1
    assert not memory_store[session_id].get(KEY_GAME_OVER, False)

    _sync_ctx(ctx, memory_store, result1)
    result2 = await handler.handle(
        req=None,
        body=ChatRequest(message="We can also schedule a follow-up appointment in a few weeks.", sessionId=session_id, coach=True),
        ctx=ctx,
    )

    assert "% overall" in result2["coach_post"]["title"]
    assert memory_store[session_id][KEY_GAME_OVER] is True
    assert "% overall" in memory_store[session_id][KEY_COACH_POST]["title"]


@pytest.mark.asyncio
async def test_replay_literature_followup_cannot_end_without_surfaced_concern():
    handler, memory_store = _handler(
        turn_results=[
            _turn(
                step="Secure",
                score=2,
                patient_reply=(
                    "I guess I can look at the literature, and we can talk about it later. "
                    "I just really want to focus on today's problem right now."
                ),
                reasons=["You offered materials and a follow-up."],
                person_topic=None,
            ),
        ],
        endgame_results=[
            {
                "is_endgame": True,
                "resolution_type": "accepted_literature",
                "summary": "Person accepted information and follow-up.",
                "reason": "",
            },
        ],
    )
    session_id = "literature-no-inquire"
    mem = {
        SESSION_HISTORY: [],
        "full_history": [],
        KEY_AIMS_STATE: {
            "announced": True,
            "phase": "Secure",
            "is_undiscovered_concerns": True,
            "pending_concerns": False,
            "parent_concerns": [],
            "recent_coaching": [],
        },
        KEY_UPDATED: time.time(),
    }
    ctx = _context(
        session_id=session_id,
        mem=mem,
        person_last="Vaccines? I thought we were here for today's problem.",
    )

    result = await handler.handle(
        req=None,
        body=ChatRequest(
            message="I can send you home with some literature and book a follow-up to talk about it.",
            sessionId=session_id,
            coach=True,
        ),
        ctx=ctx,
    )

    assert "coach_post" not in result
    assert memory_store[session_id].get(KEY_GAME_OVER, False) is False
    assert KEY_COACH_POST not in memory_store[session_id]


@pytest.mark.asyncio
async def test_replay_polite_appreciation_near_miss_does_not_end():
    handler, memory_store = _handler(
        turn_results=[
            _turn(
                step="Secure",
                score=2,
                patient_reply="That sounds fair, thank you. I appreciate you not pushing.",
                reasons=["You kept the conversation open and low-pressure."],
                person_topic=None,
            )
        ],
        endgame_results=[
            {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": "detection_error"}
        ],
    )
    session_id = "near-miss"
    mem = {
        SESSION_HISTORY: [],
        "full_history": [],
        KEY_AIMS_STATE: _resolved_trust_state(),
        KEY_UPDATED: time.time(),
    }
    ctx = _context(session_id=session_id, mem=mem, person_last="I'm still weighing things.")

    result = await handler.handle(
        req=None,
        body=ChatRequest(message="I can give you a handout if you'd like.", sessionId=session_id, coach=True),
        ctx=ctx,
    )

    assert "coach_post" not in result
    assert not memory_store[session_id].get(KEY_GAME_OVER, False)


@pytest.mark.asyncio
async def test_replay_resolved_trust_concern_does_not_reopen_on_paraphrase():
    handler, memory_store = _handler(
        turn_results=[
            _turn(
                step="Mirror+Secure",
                score=2,
                patient_reply="That explanation helps me understand how you're weighing the uncertainty.",
                reasons=["You acknowledged the concern and stayed transparent."],
                person_topic="trust",
                person_events=[
                    {
                        "event_type": "concern_renewed",
                        "topic": "trust",
                        "evidence_spans": [
                            "I'm still trying to understand the quantitative basis for those estimates."
                        ],
                    }
                ],
            )
        ],
        endgame_results=[
            {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": ""}
        ],
    )
    session_id = "resolved-concern"
    mem = {
        SESSION_HISTORY: [],
        "full_history": [],
        KEY_AIMS_STATE: _resolved_trust_state(),
        KEY_UPDATED: time.time(),
    }
    person_last = "I'm still trying to understand the quantitative basis for those estimates."
    ctx = _context(session_id=session_id, mem=mem, person_last=person_last)

    await handler.handle(
        req=None,
        body=ChatRequest(message="You're looking for a transparent account of what the numbers can and can't tell us.", sessionId=session_id, coach=True),
        ctx=ctx,
    )

    concern = memory_store[session_id][KEY_AIMS_STATE]["parent_concerns"][0]
    assert len(memory_store[session_id][KEY_AIMS_STATE]["parent_concerns"]) == 1
    assert concern["status"] == "resolved"
    assert concern["is_mirrored"] is True
    assert concern["is_secured"] is True
    assert concern["evidence"][-1].startswith("I'm still trying to understand")


@pytest.mark.asyncio
async def test_replay_mixed_resolution_vaccine_today_plus_literature_ends_as_vaccine():
    handler, memory_store = _handler(
        turn_results=[
            _turn(
                step="Secure",
                score=3,
                patient_reply=(
                    "That sounds like a reasonable plan. I'm comfortable proceeding with the Tdap today, "
                    "and I'd appreciate reading material for the others."
                ),
                reasons=["You made a concrete plan and preserved choice."],
                person_topic=None,
            )
        ],
        endgame_results=[
            {
                "is_endgame": True,
                "resolution_type": "accepted_vaccine",
                "summary": "Person agreed to one vaccine today and literature for the others.",
                "reason": "",
            }
        ],
    )
    session_id = "mixed-resolution"
    mem = {
        SESSION_HISTORY: [],
        "full_history": [],
        KEY_AIMS_STATE: _resolved_trust_state(),
        KEY_UPDATED: time.time(),
    }
    ctx = _context(session_id=session_id, mem=mem, person_last="I want to be thoughtful about this.")

    result = await handler.handle(
        req=None,
        body=ChatRequest(message="We could do the Tdap today and send you home with information on the others.", sessionId=session_id, coach=True),
        ctx=ctx,
    )

    assert "% overall" in result["coach_post"]["title"]
    assert "Outcome:" in result["coach_post"]["lines"][0]
    assert memory_store[session_id][KEY_GAME_OVER] is True


def _checklist_state_for_replay() -> dict:
    """A persona with one checklist concern that never gets discovered - reproduces
    the live-verified stuck-loop bug: the endgame backstop blocks every closing turn
    forever because nothing in this scripted conversation ever surfaces it."""
    return {
        "announced": True,
        "phase": "Secure",
        "is_undiscovered_concerns": True,
        "pending_concerns": False,
        "parent_concerns": [
            {
                "topic": "immune_load",
                "desc": "worried that several vaccines at once might be too much",
                "is_discovered": False,
                "is_mirrored": False,
                "is_secured": False,
                "from_checklist": True,
            }
        ],
        "recent_coaching": [],
    }


@pytest.mark.asyncio
async def test_replay_stuck_undiscovered_backstop_eventually_closes_after_sweep_and_literature():
    """Reproduces the live-verified bug deterministically: a persona checklist concern
    that never gets discovered blocks every closing turn forever (turns 1-4), until the
    clinician has both offered literature AND made one genuine Inquire sweep that still
    didn't surface it (turn 5) - at which point the session can finally close (turn 6)."""
    accepted_result = {
        "is_endgame": True,
        "resolution_type": "accepted_vaccine",
        "summary": "Person agreed to vaccinate today.",
        "reason": "",
    }
    handler, memory_store = _handler(
        turn_results=[
            _turn(step="Secure", score=2, patient_reply="Okay, that's a lot to take in."),
            _turn(step="Secure", score=2, patient_reply="I appreciate you explaining that."),
            _turn(step="Secure", score=2, patient_reply="Thank you for being patient."),
            _turn(step="Secure", score=2, patient_reply="I understand, thank you."),
            _turn(step="Inquire", score=2, patient_reply="No, I think that's everything."),
            _turn(step="Secure", score=2, patient_reply="Okay, let's go ahead then."),
        ],
        endgame_results=[
            accepted_result,  # turn 1: still blocked (nothing discovered yet)
            accepted_result,  # turn 2: still blocked
            accepted_result,  # turn 3: still blocked
            accepted_result,  # turn 4: still blocked
            {"is_endgame": False, "resolution_type": "not_resolved", "summary": "", "reason": ""},  # turn 5: Inquire sweep, not a closing attempt
            accepted_result,  # turn 6: bypass applies, session closes
        ],
    )
    session_id = "stuck-undiscovered-then-resolves"
    mem = {
        SESSION_HISTORY: [],
        "full_history": [],
        KEY_AIMS_STATE: _checklist_state_for_replay(),
        KEY_UPDATED: time.time(),
    }
    ctx = _context(session_id=session_id, mem=mem, person_last="I'm not sure about all these vaccines at once.")

    messages = [
        "Here's a handout with all the information to take home.",
        "We won't do the needles today; take your time.",
        "No rush at all, we'll revisit at your next visit.",
        "You too, take care.",
        "Is there anything else on your mind before you head out today?",
        "Not at all, you're welcome. Goodbye, take care.",
    ]

    results = []
    # Asserted immediately after each turn, before the next turn mutates the same
    # stored session dict - memory_store[session_id] is one mutable object across the
    # whole conversation, so checking it only after the full loop would silently read
    # back the FINAL (turn 6) state for every earlier "did it stay blocked" assertion.
    for i, msg in enumerate(messages):
        result = await handler.handle(
            req=None,
            body=ChatRequest(message=msg, sessionId=session_id, coach=True),
            ctx=ctx,
        )
        results.append(result)
        state_after = memory_store[session_id][KEY_AIMS_STATE]

        if i < 4:
            # Turns 1-4: the backstop keeps blocking closure - nothing was ever
            # discovered, so the same accepted_vaccine outcome is vetoed every time.
            assert "coach_post" not in result, f"turn {i + 1} closed prematurely"
            assert memory_store[session_id].get(KEY_GAME_OVER, False) is False
            assert state_after["endgame_blocked_undiscovered"] is True
        elif i == 4:
            # Turn 5: the genuine Inquire sweep still doesn't discover anything, but is
            # now recorded as a real attempt.
            assert "coach_post" not in result
            assert state_after["patient_unreceptive_to_further_inquire"] is True
            assert state_after["literature_offered"] is True
        else:
            # Turn 6: with a genuine sweep attempt AND literature already offered, the
            # same accepted_vaccine outcome that was blocked four times in a row now
            # closes.
            assert memory_store[session_id][KEY_GAME_OVER] is True
            assert state_after["endgame_blocked_undiscovered"] is False
            assert "% overall" in result["coach_post"]["title"]

        if i < len(messages) - 1:
            _sync_ctx(ctx, memory_store, result)
