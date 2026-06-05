from app.prompts.aims import build_endgame_detector_prompt
from app.prompts.aims import build_patient_reply_prompt


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
