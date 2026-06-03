from app.services.clinician_identity import (
    clinician_display_name_from_full_name,
    clinician_display_name_from_user_info,
)


def test_clinician_display_name_uses_last_name_from_sso_metadata():
    user_info = {
        "identifier": "craig.burnett@gmail.com",
        "metadata": {"provider": "google", "name": "Craig Burnett"},
    }

    assert clinician_display_name_from_user_info(user_info) == "Dr. Burnett"


def test_clinician_display_name_preserves_existing_doctor_title():
    assert clinician_display_name_from_full_name("Dr. Ada Lovelace") == "Dr. Ada Lovelace"


def test_clinician_display_name_missing_name_is_empty():
    assert clinician_display_name_from_user_info({"identifier": "clinician@example.com"}) == ""
