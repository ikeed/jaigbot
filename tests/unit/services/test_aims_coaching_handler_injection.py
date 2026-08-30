import logging
from unittest.mock import AsyncMock, Mock

import pytest

from app.constants import KEY_AIMS_STATE, KEY_COACH_POST, KEY_GAME_OVER, SESSION_HISTORY
from app.models import AimsObservations, ChatRequest, ClassifierResult, Coaching, FeedbackItem
from app.services.aims_coaching_handler import AimsCoachingHandler
from app.services.aims_turn_coordinator import AimsTurnResult
from app.services.chat_context import ChatContext


def _handler(
    *,
    classifier,
    patient_reply,
    metrics,
    feedback,
    endgame,
    telemetry=None,
    turn_coordinator=None,
):
    return AimsCoachingHandler(
        memory_store={},
        gemini_config={
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
        classifier_service=classifier,
        patient_reply_service=patient_reply,
        metrics_service=metrics,
        coach_feedback_history_service=feedback,
        endgame_service=endgame,
        telemetry=telemetry,
        turn_coordinator=turn_coordinator,
    )


def _basic_context() -> ChatContext:
    return ChatContext(
        session_id="sid",
        generated_session=False,
        mem={"history": [], "full_history": []},
        effective_character="Persona text",
        effective_scene="Scene text",
        system_instruction=None,
        history_text="Clinician: hello",
        person_last="",
        user_info={"identifier": "clinician@example.com", "metadata": {"name": "Craig Burnett"}},
    )


def test_build_reply_concern_state_section_distinguishes_open_and_resolved_concerns():
    section = AimsCoachingHandler._build_reply_concern_state_section(
        {
            "parent_concerns": [
                {
                    "topic": "ingredients",
                    "canonical_label": "wants vaccine ingredients addressed",
                    "is_secured": True,
                },
                {
                    "topic": "timing",
                    "summary": "wants timing addressed",
                    "is_secured": False,
                },
            ]
        }
    )

    assert "Open concerns: wants timing addressed." in section
    assert "Resolved concerns: wants vaccine ingredients addressed." in section
    assert "do not reopen resolved concerns as if unanswered" in section


def test_build_reply_concern_state_section_undiscovered_checklist_entry_only():
    """A fresh session's pre-seeded, not-yet-discovered checklist concerns must
    not be shown as 'open' -- that would tell the roleplay model to blurt them
    out unprompted, defeating the whole point of the checklist."""
    section = AimsCoachingHandler._build_reply_concern_state_section(
        {
            "parent_concerns": [
                {
                    "topic": "immune_load",
                    "desc": "Worried that several vaccines at once might be too much.",
                    "is_discovered": False,
                    "is_mirrored": False,
                    "is_secured": False,
                    "from_checklist": True,
                }
            ]
        }
    )

    assert "Open concerns" not in section
    assert "Worried that several vaccines at once might be too much." in section
    assert "have NOT brought up yet" in section
    assert "open concerns: none" not in section.lower()


def test_build_reply_concern_state_section_undiscovered_plus_resolved():
    section = AimsCoachingHandler._build_reply_concern_state_section(
        {
            "parent_concerns": [
                {
                    "topic": "autonomy",
                    "canonical_label": "wants autonomy respected",
                    "is_discovered": True,
                    "is_mirrored": True,
                    "is_secured": True,
                    "from_checklist": True,
                },
                {
                    "topic": "age_appropriateness",
                    "desc": "Worried the vaccine isn't age-appropriate.",
                    "is_discovered": False,
                    "is_mirrored": False,
                    "is_secured": False,
                    "from_checklist": True,
                },
            ]
        }
    )

    assert "Resolved concerns: wants autonomy respected." in section
    assert "Worried the vaccine isn't age-appropriate." in section
    # The fully-resolved marker must not fire while something is still undiscovered.
    assert "open concerns: none" not in section.lower()


def test_build_reply_concern_state_section_fully_resolved_has_no_open_marker_intact():
    """A checklist concern that's discovered AND secured must still hit the
    existing 'open concerns: none' marker so the patient-reply fallback picks
    the resolved-tone acknowledgement -- the new undiscovered bucket must not
    interfere with genuinely-resolved sessions."""
    section = AimsCoachingHandler._build_reply_concern_state_section(
        {
            "parent_concerns": [
                {
                    "topic": "trust",
                    "canonical_label": "wants evidence addressed",
                    "is_discovered": True,
                    "is_mirrored": True,
                    "is_secured": True,
                    "from_checklist": True,
                }
            ]
        }
    )

    assert "open concerns: none" in section.lower()


def test_build_classify_checklist_context_includes_desc_not_just_bare_topic():
    """The classifier only knows a topic's canonical meaning unless told the
    persona's specific framing -- without desc, two closely-related concerns
    (e.g. Ethan's trust="wants to see actual data" vs.
    effectiveness="wants individual vs population risk data") can both read
    as the same thing to the model. Confirmed live: without this, trust never
    got discovered across a 7-turn conversation that repeatedly asked for
    data, because the model had no way to distinguish it from effectiveness."""
    context = AimsCoachingHandler._build_classify_checklist_context(
        {
            "parent_concerns": [
                {
                    "topic": "trust",
                    "desc": "Wants to see the actual data and evidence behind the recommendation before agreeing to anything.",
                    "is_discovered": False,
                    "from_checklist": True,
                },
                {
                    "topic": "effectiveness",
                    "desc": "Wants to know whether the recommendation reflects his individual absolute risk.",
                    "is_discovered": True,
                    "from_checklist": True,
                },
            ]
        }
    )

    assert "trust (not yet discovered) -- Wants to see the actual data" in context
    assert "effectiveness (discovered) -- Wants to know whether" in context


def test_build_classify_checklist_context_handles_missing_desc_gracefully():
    context = AimsCoachingHandler._build_classify_checklist_context(
        {
            "parent_concerns": [
                {"topic": "autonomy", "is_discovered": False, "from_checklist": True},
            ]
        }
    )

    assert context == "autonomy (not yet discovered)"


def test_build_classify_checklist_context_empty_without_checklist_entries():
    assert AimsCoachingHandler._build_classify_checklist_context({"parent_concerns": []}) == ""
    assert AimsCoachingHandler._build_classify_checklist_context(None) == ""


def test_append_endgame_blocked_tip_adds_important_feedback_item_when_turn_already_structured():
    cls_payload = {
        "step": "Secure",
        "tips": [],
        "feedback_items": [
            {"step": "Secure", "tone": "praise", "code": "other", "text": "Nice work."}
        ],
    }
    AimsCoachingHandler._append_endgame_blocked_tip(cls_payload)

    items = cls_payload["feedback_items"]
    assert len(items) == 2
    new_item = next(i for i in items if i["code"] == "endgame_undiscovered_concern")
    assert new_item["step"] == "Secure"
    assert "anything else on your mind" in new_item["text"].lower()
    # Legacy tips must not also be touched when the turn is already structured.
    assert cls_payload["tips"] == []


def test_append_endgame_blocked_tip_is_idempotent():
    """Calling it twice (e.g. a defensive re-check) must not duplicate the tip."""
    cls_payload = {
        "step": "Secure",
        "feedback_items": [{"step": "Secure", "tone": "praise", "code": "other", "text": "x"}],
    }
    AimsCoachingHandler._append_endgame_blocked_tip(cls_payload)
    AimsCoachingHandler._append_endgame_blocked_tip(cls_payload)

    assert sum(1 for i in cls_payload["feedback_items"] if i["code"] == "endgame_undiscovered_concern") == 1


def test_append_endgame_blocked_tip_uses_legacy_tips_when_turn_has_no_structured_feedback():
    """A turn where the classifier omitted the optional feedback_items field (a normal
    occurrence, not just the dormant heuristic-fallback path) must fall back to
    prepending coaching.tips[0] -- appending to feedback_items here would make
    coaching_display.py silently drop this turn's own reasons/tips."""
    cls_payload = {"step": "Secure", "reasons": ["Some existing reason."], "tips": ["Existing tip."]}
    AimsCoachingHandler._append_endgame_blocked_tip(cls_payload)

    assert cls_payload.get("feedback_items") is None
    assert cls_payload["tips"][0].lower().startswith("this doesn't look fully resolved")
    assert "Existing tip." in cls_payload["tips"]
    assert cls_payload["reasons"] == ["Some existing reason."]


def test_append_endgame_blocked_tip_legacy_path_is_idempotent():
    cls_payload = {"step": "Secure", "tips": []}
    AimsCoachingHandler._append_endgame_blocked_tip(cls_payload)
    AimsCoachingHandler._append_endgame_blocked_tip(cls_payload)

    assert cls_payload["tips"].count(cls_payload["tips"][0]) == 1


def _metrics(summary=None):
    metrics = Mock()
    metrics.persist.return_value = None
    metrics.build_summary.return_value = summary or {
        "totalTurns": 1,
        "perStepCounts": {"Announce": 1},
        "runningAverage": {"Announce": 2.0},
    }
    return metrics


def _feedback():
    feedback = Mock()
    feedback.filter_user_facing_reasons.side_effect = lambda reasons, step=None: list(reasons or [])
    feedback.append.return_value = None
    return feedback


def _endgame(coach_post=None):
    endgame = Mock()
    endgame.check = AsyncMock(return_value=coach_post)
    return endgame


def _turn(
    *,
    step="Announce",
    score=2,
    reasons=None,
    tips=None,
    step_feedback=None,
    is_small_talk=False,
    patient_reply="Thanks, Doctor.",
    was_fallback=False,
    observations=None,
    feedback_items=None,
):
    classification_result = ClassifierResult(
        is_small_talk=is_small_talk,
        is_vaccine_relevant=True,
        aims=Coaching(
            step=step,
            steps=[step] if step else [],
            score=score,
            reasons=["Clear recommendation."] if reasons is None else reasons,
            tips=["Ask what questions they have."] if tips is None else tips,
            step_feedback=step_feedback or [],
            observations=observations,
            feedback_items=feedback_items or [],
        ),
        safety_flags=[],
        person_topic=None,
        reasoning="test",
    )
    return AimsTurnResult(
        cls_payload=classification_result.aims.model_dump(),
        is_vaccine_relevant=True,
        is_small_talk=is_small_talk,
        classification_result=classification_result,
        reply_payload={"patient_reply": patient_reply},
        was_fallback=was_fallback,
    )


@pytest.mark.asyncio
async def test_handle_uses_injected_services(monkeypatch):
    classify_result = ClassifierResult(
        is_small_talk=False,
        is_vaccine_relevant=True,
        aims=Coaching(
            step="Announce",
            steps=["Announce"],
            score=2,
            reasons=["Clear recommendation."],
            tips=["Ask what questions they have."],
        ),
        safety_flags=[],
        person_topic=None,
        reasoning="test",
    )
    classifier = Mock()
    classifier.classify_turn = AsyncMock(return_value=classify_result)

    patient_reply = Mock()
    patient_reply.generate = AsyncMock(return_value={"patient_reply": "Thanks, Doctor."})

    metrics = Mock()

    def persist_metrics(mem, cls_payload):
        mem["metrics_persisted"] = True

    metrics.persist.side_effect = persist_metrics
    metrics.build_summary.return_value = {
        "totalTurns": 1,
        "perStepCounts": {"Announce": 1},
        "runningAverage": {"Announce": 2.0},
    }

    feedback = Mock()
    feedback.filter_user_facing_reasons.side_effect = (
        lambda reasons, step=None: [
            reason for reason in reasons if not reason.lower().startswith("internal")
        ]
    )

    def append_feedback(**kwargs):
        kwargs["mem"]["coach_feedback_appended"] = True

    feedback.append.side_effect = append_feedback
    endgame = Mock()
    endgame.check = AsyncMock(return_value=None)
    handler = _handler(
        classifier=classifier,
        patient_reply=patient_reply,
        metrics=metrics,
        feedback=feedback,
        endgame=endgame,
    )

    async def fake_mapping():
        return {}

    monkeypatch.setattr(handler, "_load_aims_mapping", fake_mapping)

    ctx = _basic_context()

    result = await handler.handle(
        req=None,
        body=ChatRequest(message="I recommend the vaccine today.", sessionId="sid", coach=True),
        ctx=ctx,
    )

    assert result["reply"] == "Thanks, Doctor."
    assert result["coaching"]["step"] == "Announce"
    assert result["session"]["perStepCounts"]["Announce"] == 1

    classifier.classify_turn.assert_awaited_once()
    classify_call = classifier.classify_turn.await_args.kwargs
    assert classify_call["clinician_message"] == "I recommend the vaccine today."

    patient_reply.generate.assert_awaited_once()
    reply_call = patient_reply.generate.await_args.kwargs
    assert reply_call["clinician_name"] == "Dr. Burnett"
    assert reply_call["character"] == "Persona text"

    metrics.persist.assert_called_once()
    metrics.build_summary.assert_called_once()

    feedback.append.assert_called_once()
    feedback_call = feedback.append.call_args.kwargs
    assert feedback_call["session_id"] == "sid"
    assert feedback_call["reply_payload"] == {"patient_reply": "Thanks, Doctor."}

    endgame.check.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_passes_optional_semantic_coaching_fields(monkeypatch):
    feedback = _feedback()
    endgame = _endgame()
    turn_coordinator = Mock()
    turn_coordinator.run = AsyncMock(
        return_value=_turn(
            step="Mirror",
            observations=AimsObservations(
                reflection_present=True,
                accuracy_check_present=False,
                question_count=1,
            ),
            feedback_items=[
                FeedbackItem(
                    step="Mirror",
                    tone="praise",
                    code="mirror_reflection",
                    text="You mirrored the concern clearly.",
                    evidence_spans=["worried about side effects"],
                )
            ],
        )
    )

    handler = _handler(
        classifier=Mock(),
        patient_reply=Mock(),
        metrics=_metrics(),
        feedback=feedback,
        endgame=endgame,
        turn_coordinator=turn_coordinator,
    )

    async def fake_mapping():
        return {}

    monkeypatch.setattr(handler, "_load_aims_mapping", fake_mapping)

    result = await handler.handle(
        req=Mock(headers={}),
        body=ChatRequest(message="It sounds like side effects worry you.", sessionId="sid", coach=True),
        ctx=_basic_context(),
    )

    assert result["coaching"]["observations"] == {
        "question_count": 1,
        "reflection_present": True,
        "accuracy_check_present": False,
    }
    assert result["coaching"]["feedback_items"] == [
        {
            "text": "You mirrored the concern clearly.",
            "step": "Mirror",
            "tone": "praise",
            "code": "mirror_reflection",
            "evidence_spans": ["worried about side effects"],
        }
    ]


@pytest.mark.asyncio
async def test_handle_refines_fallback_coaching_when_available(monkeypatch):
    classifier = Mock()
    patient_reply = Mock()
    patient_reply.generate = AsyncMock(return_value={"patient_reply": "Thanks, Doctor."})
    metrics = _metrics()
    feedback = _feedback()
    endgame = _endgame()
    handler = _handler(
        classifier=classifier,
        patient_reply=patient_reply,
        metrics=metrics,
        feedback=feedback,
        endgame=endgame,
        turn_coordinator=Mock(),
    )

    fallback_turn = _turn(
        step="Secure",
        score=1,
        reasons=["Secure before mirroring."],
        tips=["Affirm autonomy explicitly."],
        was_fallback=True,
    )
    handler.turn_coordinator.run = AsyncMock(return_value=fallback_turn)
    handler.feedback_service = Mock()
    handler.feedback_service.refine_fallback_feedback = AsyncMock(
        return_value={
            "step": "Secure",
            "steps": ["Secure"],
            "score": 1,
            "reasons": ["You gave reassurance before naming her choice."],
            "tips": ["Name that it is her decision before offering the fact."],
            "step_feedback": [
                {
                    "step": "Secure",
                    "feedback": "You gave reassurance before naming her choice.",
                    "tone": "improvement",
                }
            ],
            "phase": "Secure",
        }
    )

    async def fake_mapping():
        return {}

    monkeypatch.setattr(handler, "_load_aims_mapping", fake_mapping)

    ctx = _basic_context()
    result = await handler.handle(
        req=None,
        body=ChatRequest(message="We can do it today.", sessionId="sid", coach=True),
        ctx=ctx,
    )

    handler.feedback_service.refine_fallback_feedback.assert_awaited_once()
    assert result["coaching"]["tips"] == ["Name that it is her decision before offering the fact."]
    assert result["coaching"]["step_feedback"][0]["feedback"] == "You gave reassurance before naming her choice."


@pytest.mark.asyncio
async def test_handle_prefers_state_feedback_item_without_rewriting_step_feedback(monkeypatch):
    feedback = _feedback()
    endgame = _endgame()
    turn_coordinator = Mock()
    turn_coordinator.run = AsyncMock(
        return_value=_turn(
            step="Secure",
            score=3,
            reasons=["LLM classified as Secure."],
            tips=[],
            observations=AimsObservations(open_concern_question_present=True),
            step_feedback=[
                {
                    "step": "Secure",
                    "tone": "improvement",
                    "feedback": "Try leading with an open question before reassurance.",
                }
            ],
        )
    )

    handler = _handler(
        classifier=Mock(),
        patient_reply=Mock(),
        metrics=_metrics(),
        feedback=feedback,
        endgame=endgame,
        turn_coordinator=turn_coordinator,
    )

    async def fake_mapping():
        return {}

    monkeypatch.setattr(handler, "_load_aims_mapping", fake_mapping)

    ctx = _basic_context()
    ctx.mem[KEY_AIMS_STATE] = {
        "phase": "PreAnnounce",
        "announced": True,
        "is_undiscovered_concerns": True,
        "parent_concerns": [],
        "recent_coaching": [],
    }

    result = await handler.handle(
        req=Mock(headers={}),
        body=ChatRequest(
            message="What concerns do you have about the MMR vaccine? It is safe and effective.",
            sessionId="sid",
            coach=True,
        ),
        ctx=ctx,
    )

    # The closure-plan tip now runs unconditionally (see AimsStateService._add_closure_plan_tip);
    # this turn is Secure with no parent_concerns and no literature/follow-up ever
    # mentioned, so it correctly nudges toward offering literature alongside the
    # pre-existing secure_before_inquire_after_question item this test is really about.
    assert result["coaching"]["feedback_items"] == [
        {
            "step": "Secure",
            "tone": "improvement",
            "code": "secure_before_inquire_after_question",
            "text": "You asked an open question, then moved into reassurance before giving them space to answer.",
        },
        {
            "step": "Secure",
            "tone": "improvement",
            "code": "offer_literature",
            "text": (
                "You haven't offered anything to take home or booked a follow-up yet; "
                "try offering some information to review, or scheduling a follow-up "
                "so they know when to bring questions back."
            ),
        },
    ]
    assert result["coaching"]["step_feedback"] == [
        {
            "step": "Secure",
            "tone": "improvement",
            "feedback": "Try leading with an open question before reassurance.",
        }
    ]
    feedback_payload = feedback.append.call_args.kwargs["cls_payload"]
    assert "Try leading with an open question" in str(feedback_payload)


@pytest.mark.asyncio
async def test_handle_continues_when_telemetry_and_metrics_fail(monkeypatch):
    telemetry = Mock()
    for method_name in (
        "classify_begin",
        "reply_begin",
        "classify_end",
        "reply_end",
        "turn_ok",
    ):
        getattr(telemetry, method_name).side_effect = RuntimeError(f"{method_name} failed")

    metrics = _metrics()
    metrics.persist.side_effect = RuntimeError("persist failed")
    metrics.build_summary.side_effect = RuntimeError("summary failed")

    feedback = _feedback()
    endgame = _endgame()
    turn_coordinator = Mock()
    turn_coordinator.run = AsyncMock(return_value=_turn(patient_reply="Okay."))

    handler = _handler(
        classifier=Mock(),
        patient_reply=Mock(),
        metrics=metrics,
        feedback=feedback,
        endgame=endgame,
        telemetry=telemetry,
        turn_coordinator=turn_coordinator,
    )

    async def fake_mapping():
        return {}

    monkeypatch.setattr(handler, "_load_aims_mapping", fake_mapping)

    result = await handler.handle(
        req=Mock(headers={}),
        body=ChatRequest(message="I recommend the vaccine today.", sessionId="sid", coach=True),
        ctx=_basic_context(),
    )

    assert result["reply"] == "Okay."
    assert result["session"] == {}
    metrics.persist.assert_called_once()
    metrics.build_summary.assert_called_once()
    endgame.check.assert_awaited_once()
    telemetry.classify_begin.assert_called_once()
    telemetry.turn_ok.assert_called_once()


@pytest.mark.asyncio
async def test_handle_small_talk_without_step_clears_coaching(monkeypatch):
    feedback = _feedback()
    endgame = _endgame()
    turn_coordinator = Mock()
    turn_coordinator.run = AsyncMock(return_value=_turn(
        step=None,
        score=None,
        reasons=["rapport only"],
        tips=[],
        is_small_talk=True,
        patient_reply="He's doing well.",
    ))

    handler = _handler(
        classifier=Mock(),
        patient_reply=Mock(),
        metrics=_metrics(summary={"totalTurns": 1}),
        feedback=feedback,
        endgame=endgame,
        turn_coordinator=turn_coordinator,
    )

    async def fake_mapping():
        return {}

    monkeypatch.setattr(handler, "_load_aims_mapping", fake_mapping)

    result = await handler.handle(
        req=Mock(headers={}),
        body=ChatRequest(message="How has he been sleeping?", sessionId="sid", coach=True),
        ctx=_basic_context(),
    )

    assert result["reply"] == "He's doing well."
    assert result["coaching"]["step"] is None
    assert result["coaching"]["score"] == 0
    assert "LLM flagged as small talk" in result["coaching"]["reasons"]


@pytest.mark.asyncio
async def test_handle_sets_coach_post_and_game_over_for_ethan_style_literature_followup(monkeypatch):
    feedback = _feedback()
    endgame = _endgame(
        coach_post={
            "title": "\U0001f389 Great job!",
            "lines": ["Outcome: Ethan agreed to review the material and revisit the decision at follow-up."],
        }
    )
    turn_coordinator = Mock()
    turn_coordinator.run = AsyncMock(
        return_value=_turn(
            step="Secure",
            score=2,
            reasons=["You supported autonomy and offered a review plan."],
            tips=["Keep anchoring the plan to his actual concern."],
            patient_reply=(
                "I'm still weighing the numbers, but I have enough to review at home, and we can "
                "talk about it again at the next appointment."
            ),
        )
    )

    handler = _handler(
        classifier=Mock(),
        patient_reply=Mock(),
        metrics=_metrics(),
        feedback=feedback,
        endgame=endgame,
        turn_coordinator=turn_coordinator,
    )

    async def fake_mapping():
        return {}

    monkeypatch.setattr(handler, "_load_aims_mapping", fake_mapping)

    ctx = _basic_context()
    ctx.mem[SESSION_HISTORY] = [
        {"role": "user", "content": "I can send you home with the evidence summary and we can revisit this in two weeks."}
    ]
    ctx.mem["aims_state"] = {
        "phase": "Secure",
        "announced": True,
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

    result = await handler.handle(
        req=Mock(headers={}),
        body=ChatRequest(message="I can send you home with the evidence summary and we can revisit this in two weeks.", sessionId="sid", coach=True),
        ctx=ctx,
    )

    assert result["coach_post"]["title"] == "\U0001f389 Great job!"
    assert ctx.mem[KEY_GAME_OVER] is True
    assert ctx.mem[KEY_COACH_POST]["title"] == "\U0001f389 Great job!"


@pytest.mark.asyncio
async def test_handle_surfaces_important_tip_and_leaves_composer_unlocked_when_endgame_backstop_blocks(
    monkeypatch,
):
    """When the Endgame backstop blocks closure (aims_endgame_service.py sets
    endgame_blocked_undiscovered on aims_state and check() returns None, exactly like
    any other non-endgame turn), the handler must: surface the Important tip in this
    turn's coaching payload, and NOT set KEY_GAME_OVER / a coach_post -- a blocked
    session must not lock the composer (this is a direct interaction with the
    already-shipped composer-lock feature and needs its own explicit test)."""
    feedback = _feedback()
    endgame = Mock()

    async def _blocking_check(mem, *_args, **_kwargs):
        # Mirrors what AimsEndgameService.check() actually does on a block: mutate
        # aims_state in place, return None like any other non-endgame turn.
        mem[KEY_AIMS_STATE]["endgame_blocked_undiscovered"] = True
        return None

    endgame.check = AsyncMock(side_effect=_blocking_check)

    turn_coordinator = Mock()
    turn_coordinator.run = AsyncMock(
        return_value=_turn(
            step="Secure",
            score=2,
            reasons=["You offered a clear next step."],
            tips=[],
            patient_reply="Okay, I think I'm ready to go ahead with it.",
            # Non-empty feedback_items so this turn is on the structured path
            # (the common case for a live LLM turn) -- exercises
            # _append_endgame_blocked_tip's feedback_items branch here; its
            # legacy tips-fallback branch is covered directly in
            # test_append_endgame_blocked_tip_uses_legacy_tips_when_turn_has_no_structured_feedback.
            feedback_items=[
                {"step": "Secure", "tone": "praise", "code": "clear_offer", "text": "Nice, clear offer."}
            ],
        )
    )

    handler = _handler(
        classifier=Mock(),
        patient_reply=Mock(),
        metrics=_metrics(),
        feedback=feedback,
        endgame=endgame,
        turn_coordinator=turn_coordinator,
    )

    async def fake_mapping():
        return {}

    monkeypatch.setattr(handler, "_load_aims_mapping", fake_mapping)

    ctx = _basic_context()
    ctx.mem[SESSION_HISTORY] = [
        {"role": "user", "content": "MMR is recommended today."},
    ]
    ctx.mem["aims_state"] = {
        "phase": "Secure",
        "announced": True,
        "is_undiscovered_concerns": True,
        "parent_concerns": [
            {
                "topic": "immune_load",
                "desc": "Worried that several vaccines at once might be too much.",
                "is_discovered": False,
                "is_mirrored": False,
                "is_secured": False,
                "from_checklist": True,
            }
        ],
    }

    result = await handler.handle(
        req=Mock(headers={}),
        body=ChatRequest(message="MMR is recommended today.", sessionId="sid", coach=True),
        ctx=ctx,
    )

    assert "coach_post" not in result
    assert KEY_GAME_OVER not in ctx.mem

    feedback_items = result["coaching"]["feedback_items"]
    assert any(item["code"] == "endgame_undiscovered_concern" for item in feedback_items)


@pytest.mark.asyncio
async def test_handle_mixed_resolution_vaccine_today_plus_literature_surfaces_coach_post(monkeypatch):
    feedback = _feedback()
    endgame = _endgame(
        coach_post={
            "title": "\U0001f389 Great job!",
            "lines": ["Outcome: Zia agreed to proceed with one vaccine today and review information on the others."],
        }
    )
    turn_coordinator = Mock()
    turn_coordinator.run = AsyncMock(
        return_value=_turn(
            step="Secure",
            score=3,
            reasons=["You made a concrete plan and preserved choice."],
            tips=[],
            patient_reply=(
                "That sounds like a reasonable plan. I'm comfortable proceeding with the Tdap today, "
                "and I'd appreciate reading material for the others."
            ),
        )
    )

    handler = _handler(
        classifier=Mock(),
        patient_reply=Mock(),
        metrics=_metrics(),
        feedback=feedback,
        endgame=endgame,
        turn_coordinator=turn_coordinator,
    )

    async def fake_mapping():
        return {}

    monkeypatch.setattr(handler, "_load_aims_mapping", fake_mapping)

    result = await handler.handle(
        req=Mock(headers={}),
        body=ChatRequest(message="We could do the Tdap today and send you home with information on the others.", sessionId="sid", coach=True),
        ctx=_basic_context(),
    )

    assert result["reply"].startswith("That sounds like a reasonable plan.")
    assert result["coach_post"]["lines"][0].startswith("Outcome:")


@pytest.mark.asyncio
async def test_handle_strips_initial_reply_headers_only_on_first_assistant_turn(monkeypatch):
    feedback = _feedback()
    endgame = _endgame()
    turn_coordinator = Mock()
    turn_coordinator.run = AsyncMock(return_value=_turn(
        patient_reply="Person: Taylor Lopez\nPurpose: Flu vaccination\nHere is my reply.",
    ))

    handler = _handler(
        classifier=Mock(),
        patient_reply=Mock(),
        metrics=_metrics(summary={"totalTurns": 1}),
        feedback=feedback,
        endgame=endgame,
        turn_coordinator=turn_coordinator,
    )

    async def fake_mapping():
        return {}

    monkeypatch.setattr(handler, "_load_aims_mapping", fake_mapping)

    result = await handler.handle(
        req=Mock(headers={}),
        body=ChatRequest(message="How are things going?", sessionId="sid", coach=True),
        ctx=_basic_context(),
    )

    assert result["reply"] == "Here is my reply."

    # Once there is prior assistant text, the handler should leave the reply alone.
    second_ctx = _basic_context()
    second_ctx = ChatContext(
        session_id=second_ctx.session_id,
        generated_session=second_ctx.generated_session,
        mem={"history": [{"role": "assistant", "content": "Existing reply"}], "full_history": []},
        effective_character=second_ctx.effective_character,
        effective_scene=second_ctx.effective_scene,
        system_instruction=second_ctx.system_instruction,
        history_text=second_ctx.history_text,
        person_last="Existing reply",
        user_info=second_ctx.user_info,
    )
    turn_coordinator.run = AsyncMock(return_value=_turn(
        patient_reply="Person: Taylor Lopez\nPurpose: Flu vaccination\nHere is my reply.",
    ))
    result = await handler.handle(
        req=Mock(headers={}),
        body=ChatRequest(message="How are things going?", sessionId="sid", coach=True),
        ctx=second_ctx,
    )

    assert result["reply"] == "Person: Taylor Lopez\nPurpose: Flu vaccination\nHere is my reply."
