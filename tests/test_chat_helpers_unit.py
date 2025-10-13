import pytest

from app.services.chat_helpers import (
    build_system_instruction,
    format_history,
    recent_context,
    extract_recent_concerns,
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
    assert lines == ["User: U4", "Assistant: A4", "User: U5", "Assistant: A5"]


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
        "Parent: Hi doctor",
        "Clinician: How are you?",
        "Parent: Worried about shots",
        ]


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
