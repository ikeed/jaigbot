from __future__ import annotations

import logging
import json

import pytest

from app.services.aims_feedback_service import AimsFeedbackService


class _FakeClient:
    last_init = None
    last_call = None

    def __init__(self, project: str, region: str, model_id: str):
        _FakeClient.last_init = {
            "project": project,
            "region": region,
            "model_id": model_id,
        }

    async def generate_text_async(self, prompt: str, **kwargs):
        _FakeClient.last_call = {"prompt": prompt, "kwargs": kwargs}
        return json.dumps(
            {
                "reasons": [
                    "You reassured her before naming that it is her decision.",
                    "The concern was about autonomy, not just safety.",
                ],
                "tips": [
                    "Name that it is her decision before giving the fact.",
                    "Then add one tailored fact and pause.",
                ],
                "step_feedback": [
                    {
                        "step": "Secure",
                        "feedback": "You reassured her before naming that it is her decision.",
                        "tone": "improvement",
                    }
                ],
                "reasoning": "Fallback coaching was too generic.",
            }
        )


@pytest.mark.asyncio
async def test_refine_fallback_feedback_uses_llm_and_keeps_shape():
    service = AimsFeedbackService(
        project_id="proj",
        region="us-central1",
        model_id="model",
        model_fallbacks=["model-2"],
        temperature=0.1,
        max_tokens=256,
        client_cls=_FakeClient,
        logger=logging.getLogger("test"),
    )

    payload = {
        "step": "Secure",
        "steps": ["Secure"],
        "score": 1,
        "reasons": ["Secure before mirroring."],
        "tips": ["Affirm autonomy explicitly."],
    }

    refined = await service.refine_fallback_feedback(
        cls_payload=payload,
        clinician_message="The vaccines are safe.",
        person_last="Is it required?",
        history_text="Clinician: hello\nPerson: is it required?",
        state={
            "announced": True,
            "phase": "Secure",
            "first_inquire_done": True,
            "pending_concerns": True,
            "recent_coaching": ["secure_before_mirror"],
            "parent_concerns": [
                {
                    "topic": "autonomy",
                    "desc": "It feels like a choice pressure problem.",
                    "is_mirrored": False,
                    "is_secured": False,
                }
            ],
        },
        character="This parent is analytical and wants evidence.",
        person_topic="autonomy",
    )

    assert _FakeClient.last_init == {
        "project": "proj",
        "region": "us-central1",
        "model_id": "model",
    }
    assert "fallback AIMS turn" in _FakeClient.last_call["prompt"]
    assert _FakeClient.last_call["kwargs"]["response_mime_type"] == "application/json"
    assert refined["step"] == "Secure"
    assert refined["score"] == 1
    assert refined["reasons"][0].startswith("You reassured her")
    assert refined["tips"] == ["Name that it is her decision before giving the fact."]
    assert refined["step_feedback"][0]["tone"] == "improvement"


@pytest.mark.asyncio
async def test_refine_fallback_feedback_is_noop_when_disabled():
    service = AimsFeedbackService(
        project_id="proj",
        region="us-central1",
        model_id="model",
        model_fallbacks=[],
        temperature=0.1,
        max_tokens=256,
        client_cls=None,
        logger=logging.getLogger("test"),
    )

    payload = {"step": "Secure", "score": 1, "reasons": ["x"], "tips": ["y"]}
    refined = await service.refine_fallback_feedback(
        cls_payload=payload,
        clinician_message="The vaccines are safe.",
        person_last="Is it required?",
        history_text="",
        state=None,
        character=None,
        person_topic=None,
    )

    assert refined is payload
