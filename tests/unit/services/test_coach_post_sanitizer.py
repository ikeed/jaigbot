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
    assert endgame_title(None, outcome="deferred") == "Session Complete"
    assert endgame_title({}) == "🎉 Great job!"
    assert endgame_title({"runningAverage": {"Announce": 3.0}}) == "🏆 Excellent job!"
    assert endgame_title({"runningAverage": {"Announce": 2.1}}) == "🎉 Great job!"
    assert endgame_title({"runningAverage": {"Announce": 1.7}}) == "👏 Good job!"
    assert endgame_title({"runningAverage": {"Announce": 1.0}}) == "💪 Nice job!"


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

    assert bullets[0] == "Overall AIMS score: 64%"
    assert any("Announce 93%" in bullet and "well done" in bullet for bullet in bullets)
    assert any("Inquire 67%" in bullet and "remaining concerns" in bullet for bullet in bullets)
    assert any("Mirror 33%" in bullet and "mirror" in bullet for bullet in bullets)
    assert any(bullet.startswith("Secure:") and "absent" not in bullet for bullet in bullets)


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
