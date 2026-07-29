from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from app.json_schemas import REPLY_SCHEMA, validate_json
from app.message_catalog import message, message_list
from app.prompts.aims import build_patient_reply_prompt
from app.services.security_guard import JailbreakGuard
from app.telemetry.events import log_event as telemetry_log_event


class ReplyValidationError(ValueError):
    """Raised when model JSON is valid but the display reply violates contract."""

    def __init__(self, message: str, validation: dict[str, Any]) -> None:
        super().__init__(message)
        self.validation = validation


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
            telemetry_log_event(
                self._logger,
                "aims_patient_reply_jailbreak_intercept",
                sessionId=session_id,
                patterns=jb_matches,
                requestBody={
                    "message": clinician_message,
                    "coach": True,
                    "sessionId": session_id,
                },
            )

            return self._fallback_payload("confused_jailbreak")

        reply_prompt = build_patient_reply_prompt(
            history_text=history_text,
            clinician_last=clinician_message,
            character=character,
            scene=scene,
            clinician_name=clinician_name,
            concern_state_section=concern_state_section,
        )
        no_open_concerns = (
            message("patient_reply.concern_state.open_none_marker")
            in (concern_state_section or "").lower()
        )
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
                validation = self._validate_reply_text(text)
                if not validation["reply_valid"]:
                    reason = (
                        "patient_reply_invalid_metadata"
                        if validation["metadata_leak_detected"]
                        else "patient_reply_invalid_instruction_echo"
                    )
                    raise ReplyValidationError(reason, validation)

                if text.lower() == "ok":
                    fallback_code = (
                        "acknowledge_resolved"
                        if no_open_concerns
                        else "acknowledge_open"
                    )
                    telemetry_log_event(
                        self._logger,
                        "aims_patient_reply_terse_ok_rewrite",
                        sessionId=session_id,
                        noOpenConcerns=no_open_concerns,
                        fallbackReplyCode=fallback_code,
                    )
                    return self._fallback_payload(fallback_code)
                return {
                    "patient_reply": text,
                    "reply_validation": validation,
                }

            except ReplyValidationError as ve:
                telemetry_log_event(
                    self._logger,
                    "aims_patient_reply_invalid_text",
                    attempt=attempt,
                    sessionId=session_id,
                    reason=str(ve),
                    **ve.validation,
                )

                if attempt == 1:
                    prompt_for_attempt = self._retry_prompt(reply_prompt)
                    continue

                fallback_code = (
                    "acknowledge_resolved"
                    if no_open_concerns
                    else "acknowledge_open"
                )
                telemetry_log_event(
                    self._logger,
                    "aims_patient_reply_fallback",
                    sessionId=session_id,
                    reason="invalid_text",
                    noOpenConcerns=no_open_concerns,
                    fallbackReplyCode=fallback_code,
                )
                return self._fallback_payload(
                    fallback_code,
                    validation={
                        **ve.validation,
                        "fallback_reply_code": fallback_code,
                    },
                )

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
                    prompt_for_attempt = self._json_retry_prompt(reply_prompt)
                    continue

                fallback_code = (
                    "acknowledge_resolved"
                    if no_open_concerns
                    else "acknowledge_open"
                )
                telemetry_log_event(
                    self._logger,
                    "aims_patient_reply_fallback",
                    sessionId=session_id,
                    reason="invalid_json",
                    noOpenConcerns=no_open_concerns,
                    fallbackReplyCode=fallback_code,
                )
                return self._fallback_payload(fallback_code)

        fallback_code = "acknowledge_resolved" if no_open_concerns else "generic_ack"
        return self._fallback_payload(fallback_code)

    @staticmethod
    def _validate_reply_text(text: str) -> dict[str, Any]:
        """Validate display text without rewriting it."""
        metadata_leak_detected = False
        for line in (text or "").splitlines():
            lowered = line.strip().lower()
            if not lowered:
                continue
            if lowered.startswith(tuple(message_list("validation.metadata_label_prefixes"))):
                metadata_leak_detected = True
                break
        normalized_text = " ".join((text or "").lower().split())
        instruction_echo_detected = any(
            marker in normalized_text
            for marker in message_list("validation.instruction_echo_markers")
        )
        return {
            "reply_valid": bool(text)
            and not metadata_leak_detected
            and not instruction_echo_detected,
            "metadata_leak_detected": metadata_leak_detected,
            "fallback_reply_code": None,
        }

    @staticmethod
    def _fallback_payload(
        fallback_code: str,
        *,
        validation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "patient_reply": message(f"patient_reply.fallbacks.{fallback_code}"),
            "reply_validation": validation
            or {
                "reply_valid": True,
                "metadata_leak_detected": False,
                "fallback_reply_code": fallback_code,
            },
        }

    @staticmethod
    def _retry_prompt(base_prompt: str) -> str:
        return message("patient_reply.retry_prompt", base_prompt=base_prompt)

    @staticmethod
    def _json_retry_prompt(base_prompt: str) -> str:
        return message("patient_reply.json_retry_prompt", base_prompt=base_prompt)
