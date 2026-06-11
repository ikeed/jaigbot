from app.core.legacy_module_resolution import (
    resolve_archive_module_id,
    resolve_thread_metadata_module_id,
)


def test_resolve_archive_module_id_prefers_explicit_generic_fields():
    assert resolve_archive_module_id(
        {"metadata": {"moduleId": "interview"}, "module": {"id": "aims"}}
    ) == "interview"


def test_resolve_archive_module_id_detects_legacy_aims_payload():
    assert resolve_archive_module_id(
        {
            "aims": {"totalTurns": 1},
            "coach_post": {"title": "Done"},
            "full_history": [],
        }
    ) == "aims"


def test_resolve_archive_module_id_returns_none_for_unknown_legacy_payload():
    assert resolve_archive_module_id({"history": [], "character": "Generic"}) is None


def test_resolve_thread_metadata_module_id_prefers_explicit_module_block():
    assert resolve_thread_metadata_module_id({"module": {"id": "interview"}}) == "interview"


def test_resolve_thread_metadata_module_id_detects_legacy_aims_thread():
    assert resolve_thread_metadata_module_id(
        {
            "personaName": "Sarah",
            "initialCard": "Scenario Briefing",
            "history": [],
            "character": "Persona",
            "scene": "Clinic",
        }
    ) == "aims"


def test_resolve_thread_metadata_module_id_returns_none_for_unknown_thread_shape():
    assert resolve_thread_metadata_module_id({"history": []}) is None
