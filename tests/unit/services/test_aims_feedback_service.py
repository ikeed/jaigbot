from __future__ import annotations

import json
import logging
from typing import Any, ClassVar

import pytest

from app.services.aims_feedback_service import AimsFeedbackService


class _FakeClient:
    last_init: ClassVar[dict[str, str] | None] = None
    last_call: ClassVar[dict[str, Any] | None] = None

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
            "is_undiscovered_concerns": False,
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


@pytest.mark.asyncio
async def test_refine_fallback_feedback_is_noop_for_unsupported_step():
    service = AimsFeedbackService(
        project_id="proj",
        region="us-central1",
        model_id="model",
        model_fallbacks=[],
        temperature=0.1,
        max_tokens=256,
        client_cls=_FakeClient,
        logger=logging.getLogger("test"),
    )

    payload = {"step": "Rapport", "score": 1, "reasons": ["x"], "tips": ["y"]}
    refined = await service.refine_fallback_feedback(
        cls_payload=payload,
        clinician_message="Hello there.",
        person_last="Hi.",
        history_text="",
        state=None,
        character=None,
        person_topic=None,
    )

    assert refined is payload


class _BrokenClient(_FakeClient):
    async def generate_text_async(self, prompt: str, **kwargs):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_refine_fallback_feedback_returns_original_payload_on_gateway_error(caplog):
    service = AimsFeedbackService(
        project_id="proj",
        region="us-central1",
        model_id="model",
        model_fallbacks=[],
        temperature=0.1,
        max_tokens=256,
        client_cls=_BrokenClient,
        logger=logging.getLogger("test"),
    )
    payload = {"step": "Secure", "score": 1, "reasons": ["x"], "tips": ["y"]}

    with caplog.at_level(logging.DEBUG):
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
    assert "fallback feedback refinement failed" in caplog.text.lower()


class _FenceClient(_FakeClient):
    async def generate_text_async(self, prompt: str, **kwargs):
        return """```json
{"reasons":["Repeated","Repeated","  "],"tips":["First tip","Second tip"],"step_feedback":["bad",{"feedback":"","tone":"praise"},{"step":"Secure","feedback":"Use autonomy language.","tone":"weird"}],"reasoning":""}
```"""


@pytest.mark.asyncio
async def test_refine_fallback_feedback_normalizes_invalid_llm_payload_shapes():
    service = AimsFeedbackService(
        project_id="proj",
        region="us-central1",
        model_id="model",
        model_fallbacks=[],
        temperature=0.1,
        max_tokens=256,
        client_cls=_FenceClient,
        logger=logging.getLogger("test"),
    )

    payload = {
        "step": "Secure",
        "steps": ["Secure"],
        "score": 1,
        "reasons": ["Fallback reason"],
        "tips": ["Fallback tip"],
    }
    refined = await service.refine_fallback_feedback(
        cls_payload=payload,
        clinician_message="The vaccines are safe.",
        person_last="Is it required?",
        history_text="history",
        state=None,
        character=None,
        person_topic="autonomy",
    )

    assert refined["reasons"] == ["Repeated"]
    assert refined["tips"] == ["First tip"]
    assert refined["step_feedback"] == [
        {
            "step": "Secure",
            "feedback": "Use autonomy language.",
            "tone": "improvement",
        }
    ]
    assert "reasoning" not in refined


def test_build_context_normalizes_parent_concerns_and_feedback_objects():
    class _FeedbackObj:
        def model_dump(self):
            return {"step": "Secure", "feedback": "Be clearer.", "tone": "improvement"}

    service = AimsFeedbackService(
        project_id="proj",
        region="us-central1",
        model_id="model",
        model_fallbacks=[],
        temperature=0.1,
        max_tokens=256,
        client_cls=_FakeClient,
        logger=logging.getLogger("test"),
    )

    context = service._build_context(
        cls_payload={
            "step": "Secure",
            "steps": ["Secure"],
            "score": 2,
            "reasons": ["reason"],
            "tips": ["tip"],
            "step_feedback": [_FeedbackObj()],
            "phase": "Secure",
        },
        clinician_message="message",
        person_last="reply",
        history_text="x" * 3000,
        state={
            "announced": True,
            "phase": "Secure",
            "is_undiscovered_concerns": False,
            "pending_concerns": True,
            "recent_coaching": ["one"],
            "parent_concerns": [
                {
                    "id": "trust:data",
                    "topic": "trust",
                    "desc": "fallback desc",
                    "summary": "",
                    "evidence": ["a", "b", "c", "d"],
                    "status": "resolved",
                    "is_mirrored": 1,
                    "is_secured": 0,
                }
            ],
        },
        character="Analytical parent",
        person_topic="trust",
    )

    concern = context["state"]["parent_concerns"][0]
    assert context["history_text"] == "x" * 2000
    assert concern["summary"] == "fallback desc"
    assert concern["evidence"] == ["b", "c", "d"]
    assert concern["is_mirrored"] is True
    assert concern["is_secured"] is False
    assert context["fallback_coaching"]["step_feedback"] == [
        {"step": "Secure", "feedback": "Be clearer.", "tone": "improvement"}
    ]


def test_normalize_step_feedback_falls_back_to_reason_or_tip():
    assert AimsFeedbackService._normalize_step_feedback(
        raw=None,
        step="Mirror",
        reasons=["Use more specific mirroring."],
        tips=[],
    ) == [
        {
            "step": "Mirror",
            "feedback": "Use more specific mirroring.",
            "tone": "improvement",
        }
    ]

    assert AimsFeedbackService._normalize_step_feedback(
        raw=[],
        step="Secure",
        reasons=[],
        tips=["Lead with autonomy first."],
    ) == [
        {
            "step": "Secure",
            "feedback": "Lead with autonomy first.",
            "tone": "improvement",
        }
    ]

    assert AimsFeedbackService._normalize_step_feedback(
        raw=[],
        step=None,
        reasons=[],
        tips=[],
    ) == []


def test_strip_json_fences_handles_fenced_and_unfenced_text():
    assert (
        AimsFeedbackService._strip_json_fences("```json\n{\"a\":1}\n```")
        == "{\"a\":1}"
    )
    assert AimsFeedbackService._strip_json_fences("```") == ""
    assert AimsFeedbackService._strip_json_fences("{\"a\":1}") == "{\"a\":1}"
