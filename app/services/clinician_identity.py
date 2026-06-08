from __future__ import annotations

from typing import Any


def clinician_display_name_from_user_info(user_info: dict[str, Any] | None) -> str:
    """Return a patient-facing clinician name from SSO metadata."""
    if not isinstance(user_info, dict):
        return ""

    metadata = user_info.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    raw_name = metadata.get("name") or user_info.get("name") or user_info.get("display_name")
    if not isinstance(raw_name, str):
        return ""

    return clinician_display_name_from_full_name(raw_name)


def clinician_display_name_from_full_name(full_name: str | None) -> str:
    """Convert an SSO full name like 'Craig Burnett' to 'Dr. Burnett'."""
    if not isinstance(full_name, str):
        return ""

    cleaned = " ".join(full_name.strip().split())
    if not cleaned:
        return ""

    lowered = cleaned.lower()
    if lowered.startswith("dr. ") or lowered.startswith("dr "):
        return cleaned

    parts = cleaned.replace(",", " ").split()
    if not parts:
        return ""

    return f"Dr. {parts[-1].strip('.')}"
