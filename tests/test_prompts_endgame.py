from app.prompts.aims import build_endgame_summary_prompt


def test_build_endgame_summary_prompt_renders_placeholders():
    metrics = {"totalTurns": 3, "perStepCounts": {"Announce": 1, "Inquire": 1, "Mirror": 1, "Secure": 0}}
    transcript = "Doctor: Hi\nPatient: Hello"
    prompt = build_endgame_summary_prompt(metrics_blob="{}".format(metrics), transcript=transcript)
    # Ensure key sections are present
    assert "Session metrics (JSON):" in prompt
    assert str(metrics) in prompt
    assert "Transcript:" in prompt
    assert transcript in prompt
