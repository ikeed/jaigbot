from unittest.mock import patch

from app.memory_store import InMemoryStore
from app.services import persona_service


def test_every_persona_has_one_to_three_well_formed_concerns():
    for persona in persona_service.load_personas():
        concerns = persona.get("concerns")
        assert concerns, f"{persona.get('name')} has no concerns"
        assert 1 <= len(concerns) <= 3, f"{persona.get('name')} has {len(concerns)} concerns"
        ids = [c.get("id") for c in concerns]
        assert len(ids) == len(set(ids)), f"{persona.get('name')} has duplicate concern ids"
        for concern in concerns:
            assert concern.get("id"), f"{persona.get('name')} concern missing id"
            assert concern.get("topic"), f"{persona.get('name')} concern missing topic"
            assert concern.get("desc"), f"{persona.get('name')} concern missing desc"


def test_fallback_persona_has_a_valid_concerns_list():
    concerns = persona_service.FALLBACK_PERSONA.get("concerns")
    assert concerns
    assert 1 <= len(concerns) <= 3
    for concern in concerns:
        assert concern.get("id") and concern.get("topic") and concern.get("desc")


def test_weighted_selection_uses_inverse_interaction_counts():
    personas = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    counts = {"A": 0, "B": 1, "C": 4}

    with patch("app.services.persona_service.random.choices") as choices:
        choices.return_value = [personas[0]]
        selected = persona_service.choose_weighted_persona(personas, counts)

    assert selected == {"name": "A"}
    args, kwargs = choices.call_args
    assert args[0] == personas
    assert kwargs["weights"] == [1.0, 0.5, 0.2]
    assert kwargs["k"] == 1


def test_persona_counts_backfill_from_loader_when_cache_empty():
    store = InMemoryStore()

    def loader(user_id, names):
        assert user_id == "doctor@example.com"
        assert "Jasmine" in names
        return {"Jasmine": 2}

    counts = persona_service.get_persona_counts("doctor@example.com", store, load_counts=loader)

    assert counts["Jasmine"] == 2
    assert store.get(persona_service.persona_counts_key("doctor@example.com"))["counts"]["Jasmine"] == 2


def test_record_persona_interaction_once_deduplicates_by_session():
    store = InMemoryStore()
    persona = {"id": 1, "name": "Jasmine"}

    assert persona_service.record_persona_interaction_once("doctor@example.com", "sid", persona, store) is True
    assert persona_service.record_persona_interaction_once("doctor@example.com", "sid", persona, store) is False

    counts = persona_service.get_cached_persona_counts("doctor@example.com", store)
    assert counts["Jasmine"] == 1


def test_extract_persona_name_from_legacy_archive_character():
    archive = {
        "config": {
            "persona": {
                "character": "Base\n\nSpecific Persona: Ethan\nDetailed Biography and Motivations: ...",
            }
        }
    }

    assert persona_service.extract_persona_name_from_archive(archive) == "Ethan"


def test_build_persona_session_fields_includes_interaction_guidance():
    persona = {
        "id": 99,
        "name": "Test",
        "patient_name": "Avery",
        "brief": "A test parent.",
        "detailed": "Detailed profile.",
        "scenario": {
            "visit_reason": "Clinic visit.",
            "detailed_instructions": "Stay in role.",
            "user_sketch": "At the clinic.",
        },
        "interaction": {
            "communication_needs": ["Needs plain language."],
            "opening_posture": "Guarded but polite.",
            "voice": "Brief and practical.",
            "response_style": "Answers directly.",
            "decision_style": "Wants time to think.",
            "secondary_agenda": "Also wants help with today's symptoms.",
            "emotional_triggers": ["Being rushed."],
            "rapport_signals": ["Asks follow-up questions."],
            "shutdown_signals": ["Becomes very brief."],
            "likely_questions": ["Is this safe?"],
            "good_clinician_moves": ["Ask permission before advising."],
            "bad_clinician_moves": ["Sound judgmental."],
            "response_style_examples": ["I just need to understand it."],
            "avoid": ["Do not lecture."],
            "trust_repair": "Ask permission before sharing facts.",
            "conversation_challenge": "May agree before understanding.",
        },
    }

    fields = persona_service.build_persona_session_fields(persona)

    assert "Behavioral Guidance:" in fields["character"]
    assert "Communication needs:" in fields["character"]
    assert "Opening posture: Guarded but polite." in fields["character"]
    assert "Voice: Brief and practical." in fields["character"]
    assert "Secondary agenda: Also wants help with today's symptoms." in fields["character"]
    assert "Emotional triggers:" in fields["character"]
    assert "- Being rushed." in fields["character"]
    assert "- Needs plain language." in fields["character"]
    assert "Trust repair: Ask permission before sharing facts." in fields["character"]
    assert fields["persona"]["name"] == "Test"
    assert fields["persona"]["patient_name"] == "Avery"


def test_build_persona_session_fields_handles_string_and_invalid_interaction_types():
    persona = {
        "id": 100,
        "name": "Test",
        "patient_name": "Avery",
        "brief": "A test parent.",
        "detailed": "Detailed profile.",
        "scenario": {
            "visit_reason": "Clinic visit.",
            "detailed_instructions": "Stay in role.",
            "user_sketch": "At the clinic.",
        },
        "interaction": {
            "communication_needs": "Needs plain language.",
            "opening_posture": ["wrong-shape"],
            "voice": {"also": "wrong-shape"},
            "response_style_examples": "I just need to understand it."
        },
    }

    fields = persona_service.build_persona_session_fields(persona)

    assert "Communication needs:" in fields["character"]
    assert "- Needs plain language." in fields["character"]
    assert "Opening posture:" not in fields["character"]
    assert "Voice:" not in fields["character"]
    assert "Response style examples: Use these as style guides only, not lines to copy verbatim." in fields["character"]
    assert "- I just need to understand it." in fields["character"]


def test_persona_scenarios_use_vaccine_relevant_entry_points():
    persona_service._load_personas_cached.cache_clear()
    personas = {persona["name"]: persona for persona in persona_service.load_personas()}

    georgina = personas["Georgina"]
    assert georgina["patient_name"] == "Dakota"
    georgina_text = " ".join(str(value) for value in georgina["scenario"].values())
    assert "HPV vaccine" in georgina_text
    assert "diarrhea" not in georgina_text
    assert "Rotavirus" not in georgina_text
    assert "Carter" not in georgina_text

    ethan_text = " ".join(str(value) for value in personas["Ethan"]["scenario"].values())
    assert "General mid-age health check" in ethan_text
    assert "immunization review" in ethan_text
    assert "prostate" not in ethan_text.lower()

    zia_text = " ".join(str(value) for value in personas["Zia"]["scenario"].values())
    assert "vaccine protocol" in zia_text
    assert "new country" in zia_text
    assert "ear infection" not in zia_text

    sarah_text = " ".join(str(value) for value in personas["Sarah"]["scenario"].values())
    assert "measles" in sarah_text
    assert "MMR booster" in sarah_text
    assert "fever" not in sarah_text
    assert "cough" not in sarah_text
    assert "watery eyes" not in sarah_text

    persona_service._load_personas_cached.cache_clear()


def test_load_personas_falls_back_when_persona_file_is_unreadable(monkeypatch):
    persona_service._load_personas_cached.cache_clear()

    class MissingPath:
        def read_text(self, encoding):
            raise OSError("missing")

    monkeypatch.setattr(persona_service, "_personas_path", lambda: MissingPath())

    assert persona_service.load_personas() == [persona_service.FALLBACK_PERSONA]

    persona_service._load_personas_cached.cache_clear()


def test_find_persona_by_name_and_id_with_missing_result(monkeypatch):
    personas = [
        {"id": 1, "name": "Jasmine"},
        {"id": "2", "name": "Ethan"},
    ]
    monkeypatch.setattr(persona_service, "load_personas", lambda: personas)

    assert persona_service.find_persona(name=" jasmine ") == personas[0]
    assert persona_service.find_persona(persona_id=2) == personas[1]
    assert persona_service.find_persona(name="missing") is None


def test_load_robust_persona_uses_name_index_random_and_fallback(monkeypatch):
    personas = [{"name": "A"}, {"name": "B"}]
    monkeypatch.setattr(persona_service, "load_personas", lambda: personas)
    monkeypatch.setattr(persona_service, "find_persona", lambda name=None, persona_id=None: {"name": "Named"} if name == "Named" else None)
    monkeypatch.setattr(persona_service.settings, "PERSONA_INDEX", 99)

    assert persona_service.load_robust_persona("Named") == {"name": "Named"}
    assert persona_service.load_robust_persona()["name"] == "B"

    monkeypatch.setattr(persona_service.settings, "PERSONA_INDEX", "bad")
    monkeypatch.setattr(persona_service.random, "choice", lambda values: values[0])
    assert persona_service.load_robust_persona()["name"] == "A"

    monkeypatch.setattr(persona_service, "load_personas", lambda: [])
    assert persona_service.load_robust_persona() == persona_service.FALLBACK_PERSONA


def test_extract_persona_name_variants_and_archive_precedence():
    assert persona_service.extract_persona_name_from_text(None) is None
    assert persona_service.extract_persona_name_from_text("Parent/Patient: Riley") == "Riley"
    assert persona_service.extract_persona_name_from_text("Persona:") is None
    assert persona_service.extract_persona_name_from_archive(None) is None
    assert persona_service.extract_persona_name_from_archive(
        {"config": {"persona": {"name": "Config Name"}}, "metadata": {"personaName": "Metadata"}}
    ) == "Config Name"
    assert persona_service.extract_persona_name_from_archive(
        {"metadata": {"personaName": "Metadata"}, "character": "Person: Character"}
    ) == "Metadata"
    assert persona_service.extract_persona_name_from_archive({"character": "Parent: Character"}) == "Character"


def test_cached_persona_counts_validation_and_store_set_paths():
    class StoreWithSet(dict):
        def set(self, key, value, *, ttl=0):
            self[key] = {"value": value, "ttl": ttl}

    store = InMemoryStore()
    assert persona_service.get_persona_counts(None, store) == {}
    store[persona_service.persona_counts_key("doctor@example.com")] = {"counts": {"A": "2", "B": None}}
    assert persona_service.get_cached_persona_counts("doctor@example.com", store) == {"A": 2, "B": 0}
    store[persona_service.persona_counts_key("invalid@example.com")] = {"counts": []}
    assert persona_service.get_cached_persona_counts("invalid@example.com", store) is None

    store_with_set = StoreWithSet()
    persona_service.save_persona_counts("doctor@example.com", {"A": 1}, store_with_set)
    saved = store_with_set[persona_service.persona_counts_key("doctor@example.com")]
    assert saved["ttl"] == 0
    assert saved["value"]["counts"] == {"A": 1}


def test_select_and_record_persona_edge_cases(monkeypatch):
    store = InMemoryStore()
    monkeypatch.setattr(persona_service.settings, "PERSONA_INDEX", None)
    monkeypatch.setattr(persona_service, "load_personas", lambda: [{"name": "A"}, {"name": "B"}])
    assert persona_service.choose_weighted_persona([], {}) == persona_service.FALLBACK_PERSONA

    monkeypatch.setattr(
        persona_service,
        "choose_weighted_persona",
        lambda personas, counts, *, exclude_name=None: personas[1],
    )

    assert persona_service.select_persona_for_user("doctor@example.com", store)["name"] == "B"
    assert persona_service.record_persona_interaction_once(None, "sid", {"name": "A"}, store) is False
    assert persona_service.record_persona_interaction_once("doctor@example.com", "", {"name": "A"}, store) is False
    assert persona_service.record_persona_interaction_once("doctor@example.com", "sid", {"name": ""}, store) is False


def test_choose_weighted_persona_excludes_last_shown_name():
    personas = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    counts = {"A": 0, "B": 0, "C": 0}

    with patch("app.services.persona_service.random.choices") as choices:
        choices.return_value = [personas[1]]
        persona_service.choose_weighted_persona(personas, counts, exclude_name="A")

    args, kwargs = choices.call_args
    assert args[0] == [personas[1], personas[2]]  # "A" excluded from the candidate pool


def test_choose_weighted_persona_falls_back_to_full_pool_when_exclude_leaves_nothing():
    # Only one persona exists and it's also the last one shown -- excluding it
    # would leave no candidates, so the exclusion is ignored rather than
    # crashing or picking nothing.
    personas = [{"name": "A"}]
    counts = {"A": 0}

    with patch("app.services.persona_service.random.choices") as choices:
        choices.return_value = [personas[0]]
        persona_service.choose_weighted_persona(personas, counts, exclude_name="A")

    args, _kwargs = choices.call_args
    assert args[0] == personas


def test_select_persona_for_user_avoids_repeating_last_persona(monkeypatch):
    store = InMemoryStore()
    monkeypatch.setattr(persona_service.settings, "PERSONA_INDEX", None)
    monkeypatch.setattr(
        persona_service,
        "load_personas",
        lambda: [{"name": "A"}, {"name": "B"}],
    )
    persona_service.save_last_persona_name("doctor@example.com", "A", store)

    captured = {}

    def fake_choose(personas, counts, *, exclude_name=None):
        captured["exclude_name"] = exclude_name
        return {"name": "B"}

    monkeypatch.setattr(persona_service, "choose_weighted_persona", fake_choose)

    selected = persona_service.select_persona_for_user("doctor@example.com", store)

    assert captured["exclude_name"] == "A"
    assert selected["name"] == "B"
    assert persona_service.get_last_persona_name("doctor@example.com", store) == "B"


def test_build_persona_session_fields_omits_vaccine_transition_note(monkeypatch):
    monkeypatch.setattr(persona_service.settings, "CHARACTER_SYSTEM", "Base character")
    monkeypatch.setattr(persona_service.settings, "SCENE_OBJECTIVES", "Base scene")
    persona = {
        "id": 1,
        "name": "Adult",
        "brief": "An adult patient.",
        "detailed": "Detailed profile.",
        "scenario": {
            "visit_reason": "Annual visit.",
            "detailed_instructions": "Stay in role.",
            "user_sketch": "At the clinic.",
        },
        "interaction": "not-a-dict",
    }

    fields = persona_service.build_persona_session_fields(persona)

    assert "Base character" in fields["character"]
    assert "Base scene" in fields["scene"]
    assert "You might want to mention vaccines" not in fields["initial_card"]
