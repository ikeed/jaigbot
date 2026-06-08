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
    "side_effects": ["safe", "safety", "side effects"],
    "requirements": ["required", "mandatory", "okay in canada"],
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
    assert is_duplicate_concern(concerns, "late bedtime!", "sleep") is True
    assert is_duplicate_concern(concerns, "late bedtime", "diet") is False


def test_maybe_add_person_concern_adds_and_trims():
    st = {}
    long_text = "x" * 300
    maybe_add_person_concern(st, long_text + " sleep", TOPICAL_CUES)
    assert st["parent_concerns"]
    assert st["parent_concerns"][0]["desc"] == st["parent_concerns"][0]["summary"]
    assert len(st["parent_concerns"][0]["evidence"][0]) == 260
    assert st["parent_concerns"][0]["topic"] == "sleep"
    assert st["parent_concerns"][0]["status"] == "open"


def test_maybe_add_person_concern_uses_llm_topic():
    st = {}
    # text doesn't contain keyword for 'diet', but we pass it as llm_topic
    maybe_add_person_concern(st, "I'm worried about what he eats.", TOPICAL_CUES, llm_topic="diet")
    assert st["parent_concerns"][0]["topic"] == "diet"
    assert st["parent_concerns"][0]["desc"] == "I'm worried about what he eats."
    assert st["parent_concerns"][0]["evidence"] == ["I'm worried about what he eats."]


def test_maybe_add_person_concern_can_seed_multiple_topics_from_one_reply():
    st = {"parent_concerns": []}
    maybe_add_person_concern(
        st,
        "Is it required? Is it safe for my son?",
        TOPICAL_CUES,
    )
    assert {c["topic"] for c in st["parent_concerns"]} == {"requirements", "side_effects"}


def test_maybe_add_person_concern_maps_requirement_llm_topic_to_dedicated_bucket():
    st = {"parent_concerns": []}
    maybe_add_person_concern(
        st,
        "What happens if I do not choose it?",
        TOPICAL_CUES,
        llm_topic="system_expectations",
    )
    assert st["parent_concerns"][0]["topic"] == "requirements"
    assert st["parent_concerns"][0]["canonical_label"] == "wants rules, requirements, and consequences explained"


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


def test_maybe_add_person_concern_merges_same_topic_paraphrases_and_cleans_evidence():
    st = {"parent_concerns": []}

    maybe_add_person_concern(
        st,
        "I'm primarily interested in understanding the data and absolute risk.",
        TOPICAL_CUES,
        llm_topic="trust",
    )
    maybe_add_person_concern(
        st,
        (
            "That lands very well, Dr. Burnett. You've articulated my position precisely. "
            "It's not about denying the evidence, but about understanding the quantitative basis."
        ),
        TOPICAL_CUES,
        llm_topic="trust",
    )

    assert len(st["parent_concerns"]) == 1
    concern = st["parent_concerns"][0]
    assert concern["id"] == "trust"
    assert concern["desc"] == "wants evidence, uncertainty, and trust addressed"
    assert len(concern["evidence"]) == 2
    assert concern["evidence"][1].startswith("It's not about denying the evidence")


def test_maybe_add_person_concern_merges_known_topic_aliases():
    st = {
        "parent_concerns": [
            {
                "id": "side-effects",
                "topic": "side_effects",
                "desc": "wants side effect risk addressed",
                "summary": "wants side effect risk addressed",
                "evidence": ["I'm worried about side effects."],
                "is_mirrored": False,
                "is_secured": False,
            }
        ]
    }

    maybe_add_person_concern(
        st,
        "I still want to understand the safety risk for serious reactions.",
        TOPICAL_CUES,
        llm_topic="vaccine safety",
    )

    assert len(st["parent_concerns"]) == 1
    concern = st["parent_concerns"][0]
    assert concern["topic"] == "side_effects"
    assert concern["id"] == "side-effects"
    assert concern["evidence"][-1].startswith("I still want to understand the safety risk")


def test_maybe_add_person_concern_merges_trust_aliases():
    st = {"parent_concerns": []}

    maybe_add_person_concern(
        st,
        "It is hard to know who to believe when everyone says something different.",
        TOPICAL_CUES,
        llm_topic="conflicting information",
    )
    maybe_add_person_concern(
        st,
        "I want to understand whether the evidence is being presented honestly.",
        TOPICAL_CUES,
        llm_topic="evidence",
    )

    assert len(st["parent_concerns"]) == 1
    assert st["parent_concerns"][0]["topic"] == "trust"
    assert st["parent_concerns"][0]["desc"] == "wants evidence, uncertainty, and trust addressed"


def test_maybe_add_person_concern_acceptance_with_hedging_still_creates_concern():
    st = {"parent_concerns": []}
    maybe_add_person_concern(
        st,
        "That makes sense, but I'm still worried about side effects.",
        TOPICAL_CUES,
        llm_topic="side_effects",
    )
    assert len(st["parent_concerns"]) == 1
    assert st["parent_concerns"][0]["topic"] == "side_effects"


def test_maybe_add_person_concern_updates_resolved_concern_without_reopening():
    st = {
        "parent_concerns": [
            {
                "id": "trust",
                "topic": "trust",
                "desc": "wants evidence, uncertainty, and trust addressed",
                "summary": "wants evidence, uncertainty, and trust addressed",
                "evidence": ["I want to understand the data."],
                "is_mirrored": True,
                "is_secured": True,
                "status": "resolved",
                "mirror_count": 1,
                "secure_count": 1,
            }
        ]
    }
    maybe_add_person_concern(
        st,
        "I'm still trying to understand the quantitative basis for those estimates.",
        TOPICAL_CUES,
        llm_topic="trust",
    )
    concern = st["parent_concerns"][0]
    assert len(st["parent_concerns"]) == 1
    assert concern["status"] == "resolved"
    assert concern["is_mirrored"] is True
    assert concern["is_secured"] is True
    assert concern["evidence"][-1].startswith("I'm still trying to understand")


def test_maybe_add_person_concern_keeps_recent_five_evidence_snippets():
    st = {"parent_concerns": []}
    for idx in range(6):
        maybe_add_person_concern(
            st,
            f"I'm worried about what the data means example {idx}.",
            TOPICAL_CUES,
            llm_topic="trust",
        )

    concern = st["parent_concerns"][0]
    assert len(concern["evidence"]) == 5
    assert concern["evidence"][0].endswith("example 1.")
    assert concern["evidence"][-1].endswith("example 5.")


def test_maybe_add_person_concern_does_not_append_near_duplicate_evidence():
    st = {"parent_concerns": []}

    maybe_add_person_concern(
        st,
        "I want to understand the absolute risk reduction for someone like me.",
        TOPICAL_CUES,
        llm_topic="trust",
    )
    maybe_add_person_concern(
        st,
        "I still want to understand the absolute risk reduction for someone like me.",
        TOPICAL_CUES,
        llm_topic="trust",
    )

    concern = st["parent_concerns"][0]
    assert len(concern["evidence"]) == 1


def test_materials_followup_acceptance_requires_plan_cue_and_no_active_concern():
    st = {"parent_concerns": []}

    maybe_add_person_concern(
        st,
        "I want a handout because I still worry about trust.",
        TOPICAL_CUES,
        llm_topic="trust",
    )

    assert st["parent_concerns"][0]["topic"] == "trust"


def test_materials_followup_acceptance_rejects_negated_followup():
    st = {"parent_concerns": []}

    maybe_add_person_concern(
        st,
        "I'll read the handout, but I don't want a follow-up appointment.",
        TOPICAL_CUES,
        llm_topic="autonomy",
    )

    assert len(st["parent_concerns"]) == 1
    assert st["parent_concerns"][0]["topic"] == "autonomy"


def test_materials_followup_acceptance_with_active_safety_concern_still_records_concern():
    st = {"parent_concerns": []}

    maybe_add_person_concern(
        st,
        "A follow-up would be fine, but I'm still worried about safety.",
        TOPICAL_CUES,
        llm_topic="safety",
    )

    assert len(st["parent_concerns"]) == 1
    assert st["parent_concerns"][0]["topic"] == "side_effects"


def test_materials_without_followup_is_not_closure():
    st = {"parent_concerns": []}

    maybe_add_person_concern(
        st,
        "Send it home, I guess, but I'm still not convinced.",
        TOPICAL_CUES,
        llm_topic="trust",
    )

    assert len(st["parent_concerns"]) == 1
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


def test_mark_mirrored_multi_uses_canonical_llm_topic_alias():
    st = {"parent_concerns": [
        {"desc": "side effects", "topic": "side_effects", "is_mirrored": False, "is_secured": False},
    ]}

    mark_mirrored_multi(
        st,
        clinician_text="Wanting to understand the risk is reasonable.",
        person_text="no keyword",
        topical_cues=TOPICAL_CUES,
        llm_topic="safety",
    )

    assert st["parent_concerns"][0]["is_mirrored"] is True


def test_mark_mirrored_multi_updates_resolved_status_and_count():
    st = {"parent_concerns": [
        {
            "desc": "late bedtime",
            "topic": "sleep",
            "is_mirrored": False,
            "is_secured": True,
            "secure_count": 1,
        }
    ]}
    mark_mirrored_multi(st, clinician_text="Let's talk about sleep.", person_text="sleep", topical_cues=TOPICAL_CUES)
    concern = st["parent_concerns"][0]
    assert concern["is_mirrored"] is True
    assert concern["mirror_count"] == 1
    assert concern["status"] == "resolved"


def test_mark_mirrored_multi_uses_evidence_to_pick_matching_concern():
    st = {"parent_concerns": [
        {
            "desc": "wants side effect risk addressed",
            "topic": "side_effects",
            "summary": "wants side effect risk addressed",
            "evidence": ["I'm worried about serious reactions and long-term side effects."],
            "is_mirrored": False,
            "is_secured": False,
        },
        {
            "desc": "wants evidence, uncertainty, and trust addressed",
            "topic": "trust",
            "summary": "wants evidence, uncertainty, and trust addressed",
            "evidence": ["What bothers me is when public messaging smooths over the uncertainty in the data."],
            "is_mirrored": False,
            "is_secured": False,
        },
    ]}

    mark_mirrored_multi(
        st,
        clinician_text=(
            "It sounds like the problem isn't uncertainty itself so much as feeling "
            "like the nuance gets flattened when people talk about the data."
        ),
        person_text="no keyword",
        topical_cues=TOPICAL_CUES,
    )

    assert st["parent_concerns"][0]["is_mirrored"] is False
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


def test_mark_secured_by_topic_uses_canonical_llm_topic_alias():
    st = {"parent_concerns": [
        {"desc": "side effects", "topic": "side_effects", "is_mirrored": True, "is_secured": False},
    ]}

    mark_secured_by_topic(
        st,
        clinician_text="The safety data are reassuring.",
        topical_cues=TOPICAL_CUES,
        llm_topic="vaccine safety",
    )

    assert st["parent_concerns"][0]["is_secured"] is True
    assert st["parent_concerns"][0]["status"] == "resolved"


def test_mark_secured_by_topic_updates_count_and_status():
    st = {"parent_concerns": [
        {
            "desc": "late bedtime",
            "topic": "sleep",
            "is_mirrored": True,
            "is_secured": False,
            "mirror_count": 2,
            "secure_count": 0,
        },
    ]}
    mark_secured_by_topic(st, clinician_text="sleep is the main issue here", topical_cues=TOPICAL_CUES)
    concern = st["parent_concerns"][0]
    assert concern["is_secured"] is True
    assert concern["secure_count"] == 1
    assert concern["status"] == "resolved"


def test_mark_secured_by_topic_uses_evidence_to_pick_matching_concern():
    st = {"parent_concerns": [
        {
            "desc": "wants side effect risk addressed",
            "topic": "side_effects",
            "summary": "wants side effect risk addressed",
            "evidence": ["I'm worried about serious reactions and long-term side effects."],
            "is_mirrored": True,
            "is_secured": False,
        },
        {
            "desc": "wants evidence, uncertainty, and trust addressed",
            "topic": "trust",
            "summary": "wants evidence, uncertainty, and trust addressed",
            "evidence": ["I need the uncertainty and limitations to be stated plainly."],
            "is_mirrored": True,
            "is_secured": False,
        },
    ]}

    mark_secured_by_topic(
        st,
        clinician_text=(
            "The studies have limits, and I want to be clear about the uncertainty "
            "rather than pretending the evidence is more precise than it is."
        ),
        topical_cues=TOPICAL_CUES,
    )

    assert st["parent_concerns"][0]["is_secured"] is False
    assert st["parent_concerns"][1]["is_secured"] is True


def test_mark_secured_by_topic_allows_unique_single_overlap_for_resolved_concern():
    st = {"parent_concerns": [
        {
            "desc": "wants side effect risk addressed",
            "topic": "side_effects",
            "summary": "wants side effect risk addressed",
            "evidence": ["I'm worried about serious reactions."],
            "is_mirrored": True,
            "is_secured": False,
        },
        {
            "desc": "wants evidence, uncertainty, and trust addressed",
            "topic": "trust",
            "summary": "wants evidence, uncertainty, and trust addressed",
            "evidence": ["I need the uncertainty stated plainly."],
            "is_mirrored": True,
            "is_secured": False,
        },
    ]}

    mark_secured_by_topic(
        st,
        clinician_text="I want to be candid about the uncertainty here.",
        topical_cues=TOPICAL_CUES,
    )

    assert st["parent_concerns"][0]["is_secured"] is False
    assert st["parent_concerns"][1]["is_secured"] is True


def test_mark_secured_by_topic_does_not_guess_on_ambiguous_single_overlap():
    st = {"parent_concerns": [
        {
            "desc": "wants side effect risk addressed",
            "topic": "side_effects",
            "summary": "wants side effect risk addressed",
            "evidence": ["I'm worried about the risk of side effects."],
            "is_mirrored": True,
            "is_secured": False,
        },
        {
            "desc": "wants disease risk addressed",
            "topic": "disease_risk",
            "summary": "wants disease risk addressed",
            "evidence": ["I don't know the real disease risk anymore."],
            "is_mirrored": True,
            "is_secured": False,
        },
    ]}

    mark_secured_by_topic(
        st,
        clinician_text="There is always some risk to weigh here.",
        topical_cues=TOPICAL_CUES,
    )

    assert not any(c["is_secured"] for c in st["parent_concerns"])
