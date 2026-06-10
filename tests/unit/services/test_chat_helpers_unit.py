from app.services.chat_helpers import (
    build_system_instruction,
    format_history,
    recent_context,
    extract_recent_concerns,
    strip_appointment_headers,
)


def test_build_system_instruction_none():
    assert build_system_instruction(None, None) is None


def test_build_system_instruction_character_only():
    s = build_system_instruction("Dr. Smith", None)
    assert "roleplaying as: Dr. Smith" in s
    assert "Stay consistent" in s


def test_build_system_instruction_scene_only():
    s = build_system_instruction(None, "Pediatric well-visit coaching")
    assert "Scene objectives/context: Pediatric well-visit coaching" in s
    assert "Stay consistent" in s


def test_build_system_instruction_both():
    s = build_system_instruction("Coach", "Guide the clinician with AIMS")
    assert "roleplaying as: Coach" in s
    assert "Scene objectives/context: Guide the clinician with AIMS" in s
    # Order should be character then scene then guidance
    parts = s.split("\n")
    assert parts[0].startswith("You are roleplaying as:")
    assert parts[1].startswith("Scene objectives/context:")


def test_format_history_limits_turns():
    turns = []
    # Build 6 user/assistant pairs (12 turns)
    for i in range(6):
        turns.append({"role": "user", "content": f"U{i}"})
        turns.append({"role": "assistant", "content": f"A{i}"})
    # With memory_max_turns=2 we should only see last 4 turns (2 pairs)
    formatted = format_history(turns, memory_max_turns=2)
    lines = formatted.split("\n")
    assert lines == ["Doctor: U4", "Assistant: A4", "Doctor: U5", "Assistant: A5"]


def test_format_history_uses_module_counted_roles():
    turns = [
        {"role": "system", "content": "meta"},
        {"role": "mentor", "content": "coach"},
        {"role": "student", "content": "Q1"},
        {"role": "interviewer", "content": "A1"},
        {"role": "mentor", "content": "coach-2"},
        {"role": "student", "content": "Q2"},
        {"role": "interviewer", "content": "A2"},
    ]

    formatted = format_history(turns, memory_max_turns=1, counted_roles=("student", "interviewer"))

    assert formatted.split("\n") == ["Assistant: coach-2", "Assistant: Q2", "Assistant: A2"]


def test_recent_context_labels_and_empty():
    # empty
    assert recent_context([], 4) == ""
    turns = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi doctor"},
        {"role": "user", "content": "How are you?"},
        {"role": "assistant", "content": "Worried about shots"},
    ]
    out = recent_context(turns, 3)
    # last 3 items
    assert out.split("\n") == [
        "Assistant: Hi doctor",
        "Doctor: How are you?",
        "Assistant: Worried about shots",
        ]


def test_strip_appointment_headers_strips_person_label():
    """'Person:' header lines (from LLM output using new terminology) must be stripped."""
    text = "Person: Taylor Lopez\nPurpose: Flu vaccination\nHere is my reply."
    out = strip_appointment_headers(text)
    assert "Person: Taylor Lopez" not in out
    assert "Purpose: Flu vaccination" not in out
    assert "Here is my reply." in out


def test_strip_appointment_headers_still_strips_parent_label():
    """Legacy 'Parent:' headers must still be stripped for backward compatibility."""
    text = "Parent: Sarah Jenkins\nPurpose: Checkup\nHello, I am here."
    out = strip_appointment_headers(text)
    assert "Parent: Sarah Jenkins" not in out
    assert "Hello, I am here." in out


def test_extract_recent_concerns_filters_parent_and_limits():
    turns = [
        {"role": "assistant", "content": "I love pizza"},
        {"role": "assistant", "content": "I'm worried about the vaccine side effects"},
        {"role": "user", "content": "Acknowledged"},
        {"role": "assistant", "content": "Too many shots on the schedule makes me nervous"},
        {"role": "assistant", "content": "What about polio dose risks?"},
        {"role": "assistant", "content": "Unrelated chit chat"},
    ]
    items = extract_recent_concerns(turns, max_items=2)
    # Should pick last two qualifying concerns (latest first, then reverse to preserve chronological among selected)
    assert items == [
        "Too many shots on the schedule makes me nervous"[:300],
        "What about polio dose risks?"[:300],
    ]
