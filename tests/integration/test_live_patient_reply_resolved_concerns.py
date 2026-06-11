"""
Focused live-LLM patient-reply regression tests.

These tests call PatientReplyService directly with the real reply-generation
prompt. They are intended for behavior changes in the simulated patient, not
for transcript replay or scoring logic.
"""
from __future__ import annotations

import logging

import pytest

from app.config import settings
from app.modules.aims.services.patient_reply_service import PatientReplyService
from app.services.persona_service import build_persona_session_fields, find_persona
from app.services.vertex_helpers import avertex_call_with_fallback_json


def _jasmine_fields() -> dict:
    persona = find_persona(name="Jasmine")
    assert persona is not None
    return build_persona_session_fields(persona)


def _service() -> PatientReplyService:
    async def caller(prompt: str, schema: dict, log_path: str, **kwargs) -> str:
        return await avertex_call_with_fallback_json(
            project=settings.PROJECT_ID,
            region=settings.VERTEX_LOCATION,
            primary_model=settings.MODEL_ID,
            fallbacks=list(settings.MODEL_FALLBACKS or []),
            temperature=kwargs.get("temperature", 0.0),
            max_tokens=kwargs.get("max_tokens", 256),
            prompt=prompt,
            system_instruction=None,
            schema=schema,
            log_path=log_path,
            logger=logging.getLogger("test.live_patient_reply"),
        )

    return PatientReplyService(
        model_json_caller=caller,
        logger=logging.getLogger("test.live_patient_reply"),
        temperature=0.0,
        max_tokens=256,
    )


@pytest.mark.live_llm
@pytest.mark.asyncio
async def test_live_patient_reply_with_all_concerns_resolved_moves_to_next_step_instead_of_reopening():
    fields = _jasmine_fields()
    result = await _service().generate(
        clinician_message=(
            "After the vaccines, it's common for babies to be a little fussier than usual, "
            "want extra cuddles, sleep more, or have some soreness where the shots were given. "
            "A mild fever can also happen in the first day or two. If Sophia seems uncomfortable, "
            "feeding her, holding her, and keeping her hydrated are often the most helpful things. "
            "If she develops a fever or seems particularly uncomfortable, give us a call and we can "
            "talk through what to do. Does that answer your question?"
        ),
        history_text=(
            "Doctor: We discussed the number of vaccines, ingredients, timing, and what diseases we are protecting Sophia from.\n"
            "Assistant: Thank you, Doctor. I really appreciate you taking the time to talk through everything with me. "
            "I'm ready to go ahead.\n"
            "Doctor: Before we get Sophia's vaccines ready, what questions do you have for me?\n"
            "Assistant: What should I do if Sophia gets a fever or is really fussy after the shots?"
        ),
        session_id="live-patient-reply-resolved-concerns",
        character=fields["character"],
        scene=fields["scene"],
        clinician_name="Dr. Burnett",
        concern_state_section=(
            "Open concerns: none. Resolved concerns: wants immune load or spacing addressed, "
            "wants timing or schedule addressed, wants vaccine ingredients addressed, "
            "wants evidence, uncertainty, and trust addressed. "
            "Do not reopen resolved concerns as if unanswered."
        ),
    )
    text = (result.get("patient_reply") or "").strip()
    lower = text.lower()

    assert text
    assert not any(
        phrase in lower
        for phrase in (
            "ingredients",
            "aluminum",
            "preservatives",
            "too many shots",
            "too much for her immune system",
            "wait a little while",
            "until she's a bit bigger",
        )
    ), text
    assert any(
        phrase in lower
        for phrase in (
            "fever",
            "fussy",
            "that helps",
            "yes",
            "thank",
            "really helps",
            "that answers",
            "i'll keep an eye",
            "i appreciate",
            "that helps",
        )
    ), text
