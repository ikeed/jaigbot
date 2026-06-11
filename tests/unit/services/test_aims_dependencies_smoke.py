import asyncio

from app.modules.aims.services import aims_dependencies as deps


def test_aims_dependency_protocols_are_defined():
    assert hasattr(deps, "ClassifierDependency")
    assert hasattr(deps, "PatientReplyDependency")
    assert hasattr(deps, "AimsMetricsDependency")
    assert hasattr(deps, "CoachFeedbackHistoryDependency")
    assert hasattr(deps, "AimsStateDependency")
    assert hasattr(deps, "AimsEndgameDependency")
    assert hasattr(deps, "AimsTelemetryDependency")
    assert hasattr(deps, "AimsFeedbackDependency")
    assert hasattr(deps, "AimsTurnCoordinatorDependency")


def test_aims_dependency_protocol_stub_methods_are_executable():
    async def run_async_protocol_methods() -> None:
        assert (
            await deps.ClassifierDependency.classify_turn(
                object(),
                clinician_message="msg",
                person_last="reply",
                history=[],
                prior_announced=False,
                prior_phase="PreAnnounce",
                mapping={},
            )
            is None
        )
        assert (
            await deps.ClassifierDependency.detect_endgame(
                object(),
                history_text="history",
                announced=True,
                inquired_concerns=[],
                mirrored_concerns=[],
                secured_concerns=[],
            )
            is None
        )
        assert (
            await deps.PatientReplyDependency.generate(
                object(),
                clinician_message="msg",
                history_text="history",
                session_id="session",
                concern_state_section="Open concerns: ingredients.",
            )
            is None
        )
        assert (
            await deps.AimsEndgameDependency.check(
                object(),
                mem={},
                reply_payload={},
                session_obj={},
                session_id="session",
            )
            is None
        )
        assert (
            await deps.AimsFeedbackDependency.refine_fallback_feedback(
                object(),
                cls_payload={},
                clinician_message="msg",
                person_last="reply",
                history_text="history",
                state={},
                character="Ethan",
                person_topic="trust",
            )
            is None
        )
        assert (
            await deps.AimsTurnCoordinatorDependency.run(
                object(),
                clinician_message="msg",
                person_last="reply",
                history=[],
                prior_announced=False,
                prior_phase="PreAnnounce",
                mapping={},
                context_turns=3,
                max_concerns=3,
                inquired_concerns_list=[],
                mirrored_concerns_list=[],
                history_text="history",
                session_id="session",
                character="Ethan",
                scene="clinic",
                clinician_name="Dr. Burnett",
                concern_state_section="Open concerns: ingredients.",
            )
            is None
        )

    assert deps.AimsMetricsDependency.persist(object(), {}, {}) is None
    assert deps.AimsMetricsDependency.build_summary(object(), {}) is None
    assert (
        deps.CoachFeedbackHistoryDependency.append(
            object(),
            mem={},
            memory_enabled=True,
            session_id="session",
            cls_payload={},
            reply_payload={},
        )
        is None
    )
    assert (
        deps.CoachFeedbackHistoryDependency.filter_user_facing_reasons(
            object(), ["reason"], step="Secure"
        )
        is None
    )
    assert (
        deps.AimsStateDependency.update(
            object(),
            {},
            {},
            "clinician message",
            "person reply",
            llm_topic="trust",
        )
        is None
    )
    assert (
        deps.AimsStateDependency.apply_coaching_guidance(
            object(),
            {},
            "Secure",
            {},
            "clinician message",
            "person reply",
            character="Ethan",
        )
        is None
    )
    assert (
        deps.AimsStateDependency.update_observational_state(
            object(), {}, "Secure", steps=["Secure"]
        )
        is None
    )
    assert (
        deps.AimsTelemetryDependency.classify_begin(
            object(),
            session_id="session",
            user_info={},
            request_id="request",
        )
        is None
    )
    assert (
        deps.AimsTelemetryDependency.reply_begin(
            object(),
            session_id="session",
            user_info={},
            request_id="request",
        )
        is None
    )
    assert (
        deps.AimsTelemetryDependency.classify_end(
            object(),
            session_id="session",
            request_id="request",
            started=0.0,
            model_used="gemini",
            step="Secure",
            score=2,
        )
        is None
    )
    assert (
        deps.AimsTelemetryDependency.reply_end(
            object(),
            session_id="session",
            request_id="request",
            started=0.0,
            model_used="gemini",
            text_len=42,
        )
        is None
    )
    assert (
        deps.AimsTelemetryDependency.turn_ok(
            object(),
            latency_ms=123,
            session_id="session",
            user_info={},
            step="Secure",
            score=2,
        )
        is None
    )

    asyncio.run(run_async_protocol_methods())
