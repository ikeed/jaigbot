from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.json_schemas import REPLY_SCHEMA, validate_json
from app.modules.aims.prompts.aims import build_patient_reply_prompt
from app.services.security_guard import JailbreakGuard
from app.telemetry.events import log_event as telemetry_log_event

REPLY_REPAIR_SUFFIX = (
    "\n\nYour previous response was invalid JSON.\n"
    "Return exactly one valid JSON object with the single top-level key "
    '"patient_reply". Do not include markdown, code fences, labels, or any extra text.'
)


class PatientReplyService:
    """Generate the roleplayed patient reply for the AIMS coaching flow."""

    def __init__(
        self,
        *,
        model_json_caller: Callable[..., Awaitable[str]],
        logger: Any,
        temperature: float,
        max_tokens: int,
        jailbreak_guard: JailbreakGuard | None = None,
    ) -> None:
        self._model_json_caller = model_json_caller
        self._logger = logger
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._jailbreak_guard = jailbreak_guard or JailbreakGuard()

    @staticmethod
    def fallback_reply(concern_state_section: str | None = None) -> dict[str, Any]:
        no_open_concerns = "open concerns: none" in (concern_state_section or "").lower()
        return {
            "patient_reply": (
                "Yes, that helps. Thank you."
                if no_open_concerns
                else "I'm not sure — I have some questions, but I'd like to hear more."
            )
        }

    async def generate(
        self,
        *,
        clinician_message: str,
        history_text: str,
        session_id: str,
        character: str | None = None,
        scene: str | None = None,
        clinician_name: str | None = None,
        concern_state_section: str | None = None,
    ) -> dict[str, Any]:
        """Generate patient reply with safety checks and jailbreak detection."""
        is_jb, jb_matches = self._jailbreak_guard.detect(clinician_message)
        if is_jb:
            confused = "Um… I'm just a parent here for my child's visit. I'm not sure what you mean — are we still talking about the checkup today?"

            telemetry_log_event(
                self._logger,
                "aims_patient_reply_jailbreak_intercept",
                sessionId=session_id,
                patterns=jb_matches,
                requestBody={
                    "message": clinician_message,
                    "moduleOptions": {"feedbackEnabled": True},
                    "sessionId": session_id,
                },
            )

            return {"patient_reply": confused}

        reply_prompt = build_patient_reply_prompt(
            history_text=history_text,
            clinician_last=clinician_message,
            character=character,
            scene=scene,
            clinician_name=clinician_name,
            concern_state_section=concern_state_section,
        )
        no_open_concerns = "open concerns: none" in (concern_state_section or "").lower()

        prompt_for_attempt = reply_prompt
        for attempt in (1, 2):
            try:
                raw = await self._model_json_caller(
                    prompt_for_attempt,
                    REPLY_SCHEMA,
                    "coach_reply",
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                )
                cand = json.loads((raw or "").strip())
                validate_json(cand, REPLY_SCHEMA)

                text = cand.get("patient_reply", "").strip()

                if text.lower() == "ok":
                    text = (
                        "Yes, that helps. Thank you."
                        if no_open_concerns
                        else "I'm not sure — I have some questions, but I'd like to hear more."
                    )
                return {"patient_reply": text}

            except Exception as ve:
                telemetry_log_event(
                    self._logger,
                    "aims_patient_reply_invalid_json",
                    attempt=attempt,
                    sessionId=session_id,
                    jsonInvalid=True,
                    error=str(ve),
                )

                if attempt == 1:
                    prompt_for_attempt = reply_prompt + REPLY_REPAIR_SUFFIX
                    continue

                return self.fallback_reply(concern_state_section)

        return self.fallback_reply(concern_state_section) if not no_open_concerns else {"patient_reply": "Yes, that helps. Thank you."}
