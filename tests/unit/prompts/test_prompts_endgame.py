from unittest.mock import patch

from app.prompts.aims import (
    build_endgame_detector_prompt,
    build_patient_reply_prompt,
    build_summary_analysis_prompt,
)


def test_endgame_detector_prompt_uses_person_not_parent():
    """endgame_detector.txt must use 'person' terminology, not 'parent'."""
    prompt = build_endgame_detector_prompt(
        history_text="Clinician: Vaccines today?\nPerson: I consent.",
        announced=True,
        inquired_concerns=[],
        mirrored_concerns=[],
        secured_concerns=[],
    )
    assert "person" in prompt.lower()
    assert "parent" not in prompt.lower()


def test_patient_reply_prompt_uses_person_not_parent_in_boilerplate():
    """aims_patient_reply.txt boilerplate must use 'person' terminology."""
    prompt = build_patient_reply_prompt(
        history_text="Clinician: Hello",
        clinician_last="Hello",
    )
    # The forbidden-labels list now includes "Person:"
    assert '"Person:"' in prompt
    # Boilerplate instructions should reference 'person', not 'parent'
    # (character_section may still say 'parent of a 2-year-old' — we only check the template text)
    lines = [ln for ln in prompt.splitlines() if "{" not in ln]  # skip unfilled placeholders
    boilerplate = "\n".join(lines)
    assert "from the person only" in boilerplate
    assert "confused person" in boilerplate


def test_patient_reply_prompt_includes_clinician_name_and_bans_placeholders():
    prompt = build_patient_reply_prompt(
        history_text="Clinician: Hello",
        clinician_last="Hello",
        clinician_name="Dr. Burnett",
    )

    assert "The clinician's name is Dr. Burnett" in prompt
    assert "you may use Doctor or Dr. Burnett" in prompt
    assert "do not address them by name in every reply" in prompt
    assert "Never output bracketed placeholder text" in prompt
    assert "[Clinician's last name]" not in prompt


def test_endgame_detector_prompt_requires_both_literature_and_followup():
    prompt = build_endgame_detector_prompt(
        history_text="Doctor: We can keep talking.\nAssistant: I'd like something to read.",
        announced=True,
        inquired_concerns=["trust"],
        mirrored_concerns=["trust"],
        secured_concerns=["trust"],
    )
    lower = prompt.lower()
    assert "accepted_literature" in lower
    assert "both elements must be present" in lower
    assert "mere interest in literature" in lower
    assert "without intent to return is not an endgame" in lower


def test_endgame_detector_prompt_rejects_deferred_as_endgame():
    prompt = build_endgame_detector_prompt(
        history_text="Doctor: We can revisit this later.\nAssistant: Maybe next time.",
        announced=True,
        inquired_concerns=[],
        mirrored_concerns=[],
        secured_concerns=[],
    )
    lower = prompt.lower()
    assert "`deferred` and `not_resolved` always set `is_endgame: false`".lower() in lower
    assert "this is not an endgame" in lower
    assert "mid-conversation hesitation" in lower


def test_endgame_detector_prompt_warns_that_concern_lists_are_incomplete():
    prompt = build_endgame_detector_prompt(
        history_text="Doctor: What worries you?\nAssistant: Side effects.",
        announced=True,
        inquired_concerns=[],
        mirrored_concerns=[],
        secured_concerns=[],
    )
    lower = prompt.lower()
    assert "concern lists may be incomplete" in lower
    assert "full transcript" in lower
    assert "do not rely on empty lists" in lower


def test_summary_analysis_builder_uses_live_template_not_endgame_summary():
    with patch("app.prompts.aims.load_and_render") as load_and_render:
        load_and_render.return_value = "ok"
        build_summary_analysis_prompt(
            metrics_blob="{}",
            mapping_blob="{}",
            transcript="Doctor: hi",
        )

    load_and_render.assert_called_once()
    assert load_and_render.call_args.args[1] == "summary_analysis.txt"
