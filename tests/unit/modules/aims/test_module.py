from types import SimpleNamespace

from app.modules.aims.module import create_aims_training_module


def test_aims_module_manifest_exposes_expected_phase1_metadata():
    settings = SimpleNamespace(redis_key_prefix="aims:prod:session:")

    module = create_aims_training_module(settings=settings)
    manifest = module.manifest

    assert manifest.id == "aims"
    assert manifest.display_name == "AIMS"
    assert manifest.chat_profile_name == "AIMSBot"
    assert manifest.storage_prefix == "aims:prod:session:"
    assert manifest.archive_schema_version == "aims-v1"
    assert manifest.supports_intro is True
    assert manifest.supports_feedback is True
    assert manifest.supports_summary is True
    assert manifest.dialogue_roles.participant_roles == ("user", "assistant")
    assert manifest.dialogue_roles.feedback_roles == ("coach",)
    assert manifest.dialogue_roles.metadata_roles == ("system",)
    assert manifest.dialogue_roles.counted_roles == ("user", "assistant")
    assert module.module_id == "aims"
    assert module.display_name == "AIMS"
    assert module.storage_prefix() == "aims:prod:session:"
    assert module.get_ui_manifest() is manifest


def test_aims_module_resume_validation_rejects_module_mismatch():
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)

    mismatch = module.resume_validation(persisted_module_id="interview")
    match = module.resume_validation(persisted_module_id="aims")

    assert mismatch.is_resumable is False
    assert "does not match" in (mismatch.reason or "")
    assert match.is_resumable is True


def test_aims_module_future_hooks_remain_explicitly_unimplemented():
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)

    for fn in (
        module.initialize_session,
        module.build_startup_payload,
        module.build_startup_artifacts,
        module.handle_turn,
        module.build_system_instruction,
        module.build_history_projection,
        module.build_summary,
        module.build_archive_payload,
        module.build_jailbreak_fallback,
    ):
        try:
            fn()
        except NotImplementedError:
            continue
        raise AssertionError(f"{fn.__name__} should raise NotImplementedError in Phase 2")


def test_aims_module_formats_generic_result_into_compatibility_payload():
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)

    payload = module.format_module_response(
        result={
            "reply": "Patient reply",
            "model": "gemini-test",
            "latency_ms": 42,
            "coaching": {"step": "Announce"},
            "session": {"totalTurns": 1},
            "coach_post": {"title": "Done", "lines": ["Good job"]},
        },
        session_id="sid-1",
    )

    assert payload["reply"] == "Patient reply"
    assert payload["text"] == "Patient reply"
    assert payload["model"] == "gemini-test"
    assert payload["modelId"] == "gemini-test"
    assert payload["latencyMs"] == 42
    assert payload["latency_ms"] == 42
    assert payload["sessionId"] == "sid-1"
    assert payload["coaching"] == {"step": "Announce"}
    assert payload["session"] == {"totalTurns": 1}
    assert payload["coachPost"] == {"title": "Done", "lines": ["Good job"]}
    assert payload["gameOver"] is True
    assert payload["completion"]["kind"] == "game_over"
