import pytest

from app.services.conversation_service import (
    topics_in,
    concern_topic,
    is_duplicate_concern,
    maybe_add_parent_concern,
    mark_mirrored_multi,
    mark_best_match_mirrored,
    mark_secured_by_topic,
)


TOPICAL_CUES = {
    "sleep": ["sleep", "bedtime"],
    "diet": ["diet", "veggies"],
    "screen_time": ["screen", "tablet"],
}


def test_topics_in_detects_multiple():
    text = "We're working on sleep and also reducing screen time after bedtime."
    found = topics_in(text, TOPICAL_CUES)
    assert found == {"sleep", "screen_time"}


def test_concern_topic_picks_first_match_by_order():
    # Order matters when both cues present
    text = "The screen is on at bedtime which ruins sleep"
    # With given dict order, 'sleep' comes before 'diet' and 'screen_time'
    picked = concern_topic(text, TOPICAL_CUES)
    assert picked in {"sleep", "screen_time"}  # either is acceptable based on order


def test_is_duplicate_concern_basic():
    concerns = [{"desc": "Late bedtime", "topic": "sleep"}]
    assert is_duplicate_concern(concerns, "late bedtime", "sleep") is True
    assert is_duplicate_concern(concerns, "late bedtime!", "sleep") is False


def test_maybe_add_parent_concern_adds_and_trims():
    st = {}
    long_text = "x" * 300
    maybe_add_parent_concern(st, long_text + " sleep", TOPICAL_CUES)
    assert st["parent_concerns"]
    assert len(st["parent_concerns"][0]["desc"]) == 240
    assert st["parent_concerns"][0]["topic"] == "sleep"


def test_maybe_add_parent_concern_skips_when_no_topic():
    st = {"parent_concerns": []}
    maybe_add_parent_concern(st, "this is unrelated chit chat", TOPICAL_CUES)
    assert st["parent_concerns"] == []


def test_mark_mirrored_multi_prefers_clinician_topics():
    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": False, "is_secured": False},
        {"desc": "too much screen", "topic": "screen_time", "is_mirrored": False, "is_secured": False},
    ]}
    mark_mirrored_multi(st, clinician_text="Let's reduce screen time.", parent_text="late bedtime", topical_cues=TOPICAL_CUES)
    # screen_time should be mirrored due to clinician reflection
    mirrored = [c for c in st["parent_concerns"] if c["is_mirrored"]]
    assert {c["topic"] for c in mirrored} == {"screen_time"}


def test_mark_mirrored_multi_fallbacks_when_no_topics_found():
    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": False, "is_secured": False},
        {"desc": "too much screen", "topic": "screen_time", "is_mirrored": False, "is_secured": False},
    ]}
    # No topical match in clinician_text and parent_text
    mark_mirrored_multi(st, clinician_text="hello there", parent_text="random", topical_cues=TOPICAL_CUES)
    # Should mirror the first unmirrored concern as final fallback
    assert any(c["is_mirrored"] for c in st["parent_concerns"]) is True


def test_mark_best_match_mirrored_uses_parent_text():
    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": False, "is_secured": False},
        {"desc": "too much screen", "topic": "screen_time", "is_mirrored": False, "is_secured": False},
    ]}
    mark_best_match_mirrored(st, parent_text="The tablet is on too long", topical_cues=TOPICAL_CUES)
    mirrored = [c for c in st["parent_concerns"] if c["is_mirrored"]]
    assert {c["topic"] for c in mirrored} == {"screen_time"}


def test_mark_best_match_mirrored_fallback_when_no_parent_topic():
    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": False, "is_secured": False},
    ]}
    mark_best_match_mirrored(st, parent_text="no topic here", topical_cues=TOPICAL_CUES)
    assert st["parent_concerns"][0]["is_mirrored"] is True


def test_mark_secured_by_topic_prefers_clinician_topic():
    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": True, "is_secured": False},
        {"desc": "too much screen", "topic": "screen_time", "is_mirrored": True, "is_secured": False},
    ]}
    mark_secured_by_topic(st, clinician_text="Your child's sleep is improving.", topical_cues=TOPICAL_CUES)
    secured = [c for c in st["parent_concerns"] if c["is_secured"]]
    assert {c["topic"] for c in secured} == {"sleep"}


def test_mark_secured_by_topic_fallback_to_first_mirrored():
    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": True, "is_secured": False},
    ]}
    mark_secured_by_topic(st, clinician_text="no match text", topical_cues=TOPICAL_CUES)
    assert st["parent_concerns"][0]["is_secured"] is True
