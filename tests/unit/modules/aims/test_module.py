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


def test_aims_module_resume_validation_rejects_module_mismatch():
    settings = SimpleNamespace(redis_key_prefix="aims:local:session:")
    module = create_aims_training_module(settings=settings)

    mismatch = module.resume_validation(persisted_module_id="interview")
    match = module.resume_validation(persisted_module_id="aims")

    assert mismatch.is_resumable is False
    assert "does not match" in (mismatch.reason or "")
    assert match.is_resumable is True
