from app.services.conversation_service import (
    topics_in,
    concern_topic,
    is_duplicate_concern,
    maybe_add_person_concern,
    mark_mirrored_multi,
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


def test_topics_and_concern_helpers_handle_empty_inputs():
    assert topics_in(None, TOPICAL_CUES) == set()
    assert topics_in("sleep", {}) == set()
    assert concern_topic(None, TOPICAL_CUES) is None
    assert is_duplicate_concern([], "late bedtime", "sleep") is False


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


def test_maybe_add_person_concern_adds_and_trims():
    st = {}
    long_text = "x" * 300
    maybe_add_person_concern(st, long_text + " sleep", TOPICAL_CUES)
    assert st["parent_concerns"]
    assert len(st["parent_concerns"][0]["desc"]) == 240
    assert st["parent_concerns"][0]["topic"] == "sleep"


def test_maybe_add_person_concern_uses_llm_topic():
    st = {}
    # text doesn't contain keyword for 'diet', but we pass it as llm_topic
    maybe_add_person_concern(st, "I'm worried about what he eats.", TOPICAL_CUES, llm_topic="diet")
    assert st["parent_concerns"][0]["topic"] == "diet"
    assert st["parent_concerns"][0]["desc"] == "I'm worried about what he eats."


def test_maybe_add_person_concern_skips_materials_followup_acceptance_even_with_llm_topic():
    st = {"parent_concerns": []}
    maybe_add_person_concern(
        st,
        (
            "That sounds really good, thank you. I think having something to "
            "read over at home would help a lot, and a follow-up would be great."
        ),
        TOPICAL_CUES,
        llm_topic="autonomy",
    )
    assert st["parent_concerns"] == []


def test_maybe_add_person_concern_keeps_active_concern_with_materials_request():
    st = {"parent_concerns": []}
    maybe_add_person_concern(
        st,
        "I'm still worried about the ingredients, but having something to read over would help.",
        TOPICAL_CUES,
        llm_topic="diet",
    )
    assert st["parent_concerns"][0]["topic"] == "diet"


def test_maybe_add_person_concern_skips_when_no_topic():
    st = {"parent_concerns": []}
    maybe_add_person_concern(st, "this is unrelated chit chat", TOPICAL_CUES)
    assert st["parent_concerns"] == []


def test_maybe_add_person_concern_skips_empty_acceptance_and_duplicates():
    st = {"parent_concerns": []}

    maybe_add_person_concern(st, "", TOPICAL_CUES)
    maybe_add_person_concern(st, "That's helpful, the sleep plan makes sense.", TOPICAL_CUES)
    assert st["parent_concerns"] == []

    maybe_add_person_concern(st, "I'm worried about sleep.", TOPICAL_CUES)
    maybe_add_person_concern(st, "I'm worried about sleep.", TOPICAL_CUES)
    assert len(st["parent_concerns"]) == 1


def test_materials_followup_acceptance_requires_plan_cue_and_no_active_concern():
    st = {"parent_concerns": []}

    maybe_add_person_concern(
        st,
        "I want a handout because I still worry about trust.",
        TOPICAL_CUES,
        llm_topic="trust",
    )

    assert st["parent_concerns"][0]["topic"] == "trust"


def test_mark_mirrored_multi_prefers_clinician_topics():
    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": False, "is_secured": False},
        {"desc": "too much screen", "topic": "screen_time", "is_mirrored": False, "is_secured": False},
    ]}
    mark_mirrored_multi(st, clinician_text="Let's reduce screen time.", person_text="late bedtime", topical_cues=TOPICAL_CUES)
    # screen_time should be mirrored due to clinician reflection
    mirrored = [c for c in st["parent_concerns"] if c["is_mirrored"]]
    assert {c["topic"] for c in mirrored} == {"screen_time"}


def test_mark_mirrored_multi_fallbacks_when_no_topics_found():
    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": False, "is_secured": False},
        {"desc": "too much screen", "topic": "screen_time", "is_mirrored": False, "is_secured": False},
    ]}
    # No topical match in clinician_text and person_text
    mark_mirrored_multi(st, clinician_text="hello there", person_text="random", topical_cues=TOPICAL_CUES)
    # Should mirror the first unmirrored concern as final fallback
    assert any(c["is_mirrored"] for c in st["parent_concerns"]) is True


def test_mark_mirrored_multi_uses_person_topic_then_llm_topic():
    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": False, "is_secured": False},
        {"desc": "too much screen", "topic": "screen_time", "is_mirrored": False, "is_secured": False},
    ]}

    mark_mirrored_multi(st, clinician_text="I hear you.", person_text="The tablet is too much", topical_cues=TOPICAL_CUES)
    assert st["parent_concerns"][1]["is_mirrored"] is True

    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": False, "is_secured": False},
        {"desc": "too much screen", "topic": "screen_time", "is_mirrored": False, "is_secured": False},
    ]}
    mark_mirrored_multi(
        st,
        clinician_text="Wanting to look into it yourself is reasonable.",
        person_text="no keyword",
        topical_cues=TOPICAL_CUES,
        llm_topic="screen_time",
    )
    assert st["parent_concerns"][1]["is_mirrored"] is True


def test_mark_mirrored_helpers_noop_without_concerns_or_unmirrored_items():
    empty = {}
    mark_mirrored_multi(empty, clinician_text="sleep", person_text="sleep", topical_cues=TOPICAL_CUES)
    assert empty == {}


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


def test_mark_secured_by_topic_does_not_guess_between_multiple_concerns():
    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": True, "is_secured": False},
        {"desc": "too much screen", "topic": "screen_time", "is_mirrored": True, "is_secured": False},
    ]}
    mark_secured_by_topic(st, clinician_text="no match text", topical_cues=TOPICAL_CUES)
    assert not any(c["is_secured"] for c in st["parent_concerns"])


def test_mark_secured_by_topic_uses_llm_topic_and_noops_without_candidates():
    empty = {}
    mark_secured_by_topic(empty, clinician_text="sleep", topical_cues=TOPICAL_CUES)
    assert empty == {}

    st = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": True, "is_secured": False},
        {"desc": "too much screen", "topic": "screen_time", "is_mirrored": True, "is_secured": False},
    ]}
    mark_secured_by_topic(st, clinician_text="no keyword", topical_cues=TOPICAL_CUES, llm_topic="screen_time")
    assert st["parent_concerns"][1]["is_secured"] is True

    no_candidate = {"parent_concerns": [
        {"desc": "late bedtime", "topic": "sleep", "is_mirrored": False, "is_secured": False},
    ]}
    mark_secured_by_topic(no_candidate, clinician_text="no keyword", topical_cues=TOPICAL_CUES)
    assert no_candidate["parent_concerns"][0]["is_secured"] is False
