from app.services.coach_post import (
    AimsPostProcessor,
    EndGameDetector,
    VaccineRelevanceGate,
    build_endgame_bullets_fallback,
    endgame_title,
    sanitize_endgame_bullets,
)


def test_sanitize_endgame_bullets_filters_json_like_lines():
    raw = [
        "- Strength: Clear Announce with a concise plan.",
        "{",
        '  "patient_reply": "Parent: Sarah Jenkins"',
        '  "score": 3,',
        "}",
        "- Growth: Inquire could go deeper.",
        "```json",
        '{"foo": "bar"}',
        "```",
        "- Example: Try, 'What else is on your mind about MMR?'",
    ]
    cleaned = sanitize_endgame_bullets(raw)
    # Should remove braces, code fences, and key/value lines, and keep only meaningful bullets
    assert "Strength: Clear Announce with a concise plan." in cleaned
    assert "Growth: Inquire could go deeper." in cleaned
    assert any("What else is on your mind" in x for x in cleaned)
    # Ensure JSON-like artifacts are removed
    assert not any(x.strip() in ("{", "}") for x in cleaned)
    assert not any(":" in x and '"' in x for x in cleaned)


def test_endgame_fallback_inquire_mid_feedback_is_not_generic_stacked_question_warning():
    session_obj = {
        "perStepCounts": {"Announce": 1, "Inquire": 3, "Mirror": 4, "Secure": 5},
        "runningAverage": {
            "Announce": 3.0,
            "Inquire": 2.3333333333333335,
            "Mirror": 2.75,
            "Secure": 2.6,
        },
    }

    bullets = build_endgame_bullets_fallback(session_obj)
    inquire = next(b for b in bullets if b.startswith("Inquire "))

    assert "remaining concerns" in inquire
    assert "single-barreled" not in inquire
    assert "multiple options" not in inquire


def test_endgame_fallback_secure_leads_with_unmirrored_warning_when_present():
    session_obj = {
        "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 5},
        "runningAverage": {
            "Announce": 3.0,
            "Inquire": 3.0,
            "Mirror": 3.0,
            "Secure": 2.9,
        },
        "secureBeforeMirrorCount": 3,
    }

    bullets = build_endgame_bullets_fallback(session_obj)
    secure = next(b for b in bullets if b.startswith("Secure "))

    assert "3 times this session" in secure
    assert "before mirroring" in secure
    assert "feel heard" in secure
    # The high-score generic praise text must not also appear once the warning wins out.
    assert "well-tailored" not in secure


def test_endgame_fallback_secure_names_the_specific_concern_when_only_one_miss():
    session_obj = {
        "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 2},
        "runningAverage": {
            "Announce": 3.0,
            "Inquire": 3.0,
            "Mirror": 3.0,
            "Secure": 2.9,
        },
        "secureBeforeMirrorCount": 1,
        "secureBeforeMirrorTopicHint": " about side-effect concerns",
    }

    bullets = build_endgame_bullets_fallback(session_obj)
    secure = next(b for b in bullets if b.startswith("Secure "))

    assert "the concern about side-effect concerns" in secure
    assert "1 time this session" not in secure


def test_endgame_fallback_secure_falls_back_to_count_text_when_topic_hint_missing():
    session_obj = {
        "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 2},
        "runningAverage": {
            "Announce": 3.0,
            "Inquire": 3.0,
            "Mirror": 3.0,
            "Secure": 2.9,
        },
        "secureBeforeMirrorCount": 1,
    }

    bullets = build_endgame_bullets_fallback(session_obj)
    secure = next(b for b in bullets if b.startswith("Secure "))

    assert "1 time this session" in secure


def test_endgame_fallback_secure_uses_normal_tier_text_when_never_unmirrored():
    session_obj = {
        "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 2},
        "runningAverage": {
            "Announce": 3.0,
            "Inquire": 3.0,
            "Mirror": 3.0,
            "Secure": 3.0,
        },
        "secureBeforeMirrorCount": 0,
    }

    bullets = build_endgame_bullets_fallback(session_obj)
    secure = next(b for b in bullets if b.startswith("Secure "))

    assert "without mirroring" not in secure
    assert "well-tailored" in secure


def test_aims_post_processor_normalizes_score_and_softens_autonomy_feedback():
    payload = {
        "step": "Secure",
        "score": 0,
        "reasons": ["This sounds leading.", "Use less judgment."],
    }

    processed = AimsPostProcessor.post_process(
        payload,
        "No pressure. It is your decision, and I am happy to answer any questions.",
        allow_text_softening=True,
    )

    assert processed["score"] == 1
    assert processed["reasons"] == ["Keep framing neutral and open; invite questions."]
    assert payload["score"] == 0


def test_aims_post_processor_keeps_non_aims_score_and_filters_mixed_reasons():
    payload = {
        "step": None,
        "score": 0,
        "reasons": ["Useful feedback.", "This is leading."],
    }

    processed = AimsPostProcessor.post_process(
        payload,
        "It's up to you.",
        allow_text_softening=True,
    )

    assert processed["score"] == 0
    assert processed["reasons"] == ["Useful feedback."]


def test_aims_post_processor_preserves_reasons_when_structured_feedback_exists():
    payload = {
        "step": "Secure",
        "score": 0,
        "reasons": ["This sounds leading."],
        "feedback_items": [
            {
                "step": "Secure",
                "tone": "improvement",
                "code": "add_autonomy_support",
                "text": "Name that it is their decision.",
            }
        ],
    }

    processed = AimsPostProcessor.post_process(payload, "It's up to you.")

    assert processed["score"] == 1
    assert processed["reasons"] == ["This sounds leading."]


def test_vaccine_relevance_gate_prefers_semantic_relevance_true():
    payload = {"step": "Mirror", "score": 3, "reasons": ["Mirrored."], "tips": []}

    result = VaccineRelevanceGate.gate(
        cls_payload=payload,
        clinician_text="I hear that this feels like a lot.",
        person_last="Yes.",
        parent_recent_concerns=[],
        prior_announced=False,
        semantic_is_vaccine_relevant=True,
    )

    assert result is payload
    assert result["step"] == "Mirror"


def test_vaccine_relevance_gate_prefers_semantic_relevance_false():
    payload = {"step": "Announce", "score": 3, "reasons": ["Clear."], "tips": []}

    result = VaccineRelevanceGate.gate(
        cls_payload=payload,
        clinician_text="I recommend the MMR today.",
        person_last="Okay.",
        parent_recent_concerns=[],
        prior_announced=False,
        semantic_is_vaccine_relevant=False,
    )

    assert result["step"] is None
    assert result["score"] == 0


def test_endgame_detector_guards_conditional_and_question_acceptance():
    assert EndGameDetector.detect("If we go ahead with it today, what side effects should I expect?") is None
    assert EndGameDetector.detect("Should we go ahead with it today?") is None
    assert EndGameDetector.detect("If we go ahead, I consent to the vaccine today.") == {
        "reason": "accepted_now"
    }


def test_endgame_detector_accepts_ready_to_go_ahead_phrasings():
    assert EndGameDetector.detect("I'm ready to go ahead.") == {"reason": "accepted_now"}
    assert EndGameDetector.detect("I think I'm ready to go ahead with it for Sophia.") == {
        "reason": "accepted_now"
    }


def test_sanitize_endgame_bullets_handles_empty_quotes_duplicates_and_cap():
    raw = [
        "''",
        '""',
        "patient{bad",
        "patient_reply: bad",
        "- Keep this",
        "- Keep this",
        *[f"- Item {i}" for i in range(20)],
    ]

    cleaned = sanitize_endgame_bullets(raw)

    assert cleaned[0] == "Keep this"
    assert cleaned.count("Keep this") == 1
    assert len(cleaned) == 8
    assert not any("patient" in item for item in cleaned)


def test_endgame_title_score_tiers_and_deferred_fallback():
    """Title folds the Overall score into the same line; the bottom two tiers
    (keep_practicing, needs_work) use encouraging-but-not-celebratory language
    and emoji, since a weak score should not read as "job!" praise."""
    def _uniform(score):
        return {"runningAverage": {s: score for s in ("Announce", "Inquire", "Mirror", "Secure")}}

    assert endgame_title(None, outcome="deferred") == "Session Complete"
    assert endgame_title({}) == "🎉 Great job!"
    assert endgame_title(_uniform(3.0)) == "🏆 Excellent job — 100% overall"
    assert endgame_title(_uniform(2.1)) == "🎉 Great job — 70% overall"
    assert endgame_title(_uniform(1.7)) == "👏 Good job — 57% overall"
    assert endgame_title(_uniform(1.2)) == "💪 Keep practicing — 40% overall"
    assert endgame_title(_uniform(0.5)) == "📋 Needs work — 17% overall"


def test_endgame_title_penalizes_core_steps_that_were_never_attempted():
    """Skipping a core step entirely (e.g. Mirror never happened) must cost at
    least as much as doing it badly - it must not be excluded from the average."""
    assert endgame_title({"runningAverage": {"Announce": 3.0}}) == "📋 Needs work — 25% overall"


def test_build_endgame_bullets_fallback_handles_absent_low_mid_high_and_invalid_input():
    assert build_endgame_bullets_fallback(None)[0].startswith("Announce:")

    bullets = build_endgame_bullets_fallback(
        {
            "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 0},
            "runningAverage": {
                "Announce": 2.8,
                "Inquire": 2.0,
                "Mirror": 1.0,
                "Secure": "bad",
            },
        }
    )

    assert bullets[0] == "**Overall AIMS score:** 48%"
    assert any("Announce 93%" in bullet and "well done" in bullet for bullet in bullets)
    assert any("Inquire 67%" in bullet and "remaining concerns" in bullet for bullet in bullets)
    assert any("Mirror 33%" in bullet and "mirror" in bullet for bullet in bullets)
    assert any(bullet.startswith("Secure 0%") and "absent" not in bullet for bullet in bullets)


def test_build_endgame_bullets_fallback_can_omit_overall_score_line():
    """AimsEndgameService.check() passes include_overall_score=False because the
    score is already folded into endgame_title() - it must not appear twice."""
    bullets = build_endgame_bullets_fallback(
        {
            "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 1},
            "runningAverage": {"Announce": 2.0, "Inquire": 2.0, "Mirror": 2.0, "Secure": 2.0},
        },
        include_overall_score=False,
    )

    assert not any("Overall AIMS score" in bullet for bullet in bullets)


def test_build_endgame_bullets_fallback_personalizes_with_persona_and_patient_names():
    bullets = build_endgame_bullets_fallback(
        {
            "personaName": "Zia",
            "patientName": "Nathaniel",
            "perStepCounts": {"Announce": 1, "Inquire": 3, "Mirror": 1, "Secure": 1},
            "runningAverage": {
                "Announce": 1.0,
                "Inquire": 3.0,
                "Mirror": 1.0,
                "Secure": 3.0,
            },
        }
    )

    announce = next(b for b in bullets if b.startswith("Announce "))
    inquire = next(b for b in bullets if b.startswith("Inquire "))
    mirror = next(b for b in bullets if b.startswith("Mirror "))

    assert "Nathaniel's due for the recommended vaccine today" in announce
    assert "Carter" not in announce
    assert "Zia's real concerns" in inquire
    assert "Zia's concern" in mirror
