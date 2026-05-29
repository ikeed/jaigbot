from unittest.mock import patch

from app.memory_store import InMemoryStore
from app.services import persona_service


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
