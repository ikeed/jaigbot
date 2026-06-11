from __future__ import annotations

import datetime
import time
from dataclasses import dataclass
from typing import Any, Mapping, cast

from app.chat_roles import ROLE_ASSISTANT, ROLE_COACH, ROLE_SYSTEM, ROLE_USER
from app.core.archive_types import ArchiveCompatibilityPayload, ModuleArchiveEnvelope
from app.core.session_serialization import serialize_session_bootstrap_payload
from app.core.session_types import SessionBootstrapPayload, StartupArtifact
from app.core.response_serialization import game_over_completion, serialize_response_envelope
from app.core.response_types import ModuleResponseEnvelope
from app.core.module_types import BrandingSpec, DialogueRoles, ModuleManifest, ResumeValidationResult


@dataclass(frozen=True)
class AimsTrainingModule:
    """AIMS implementation of the generic training-module contract."""

    manifest: ModuleManifest

    @property
    def module_id(self) -> str:
        return self.manifest.id

    @property
    def display_name(self) -> str:
        return self.manifest.display_name

    def storage_prefix(self) -> str:
        return self.manifest.storage_prefix

    def dialogue_roles(self) -> DialogueRoles:
        return self.manifest.dialogue_roles

    def get_ui_manifest(self) -> ModuleManifest:
        return self.manifest

    def resume_validation(self, *, persisted_module_id: str | None = None, **kwargs: Any) -> ResumeValidationResult:
        if persisted_module_id and persisted_module_id != self.module_id:
            return ResumeValidationResult(
                is_resumable=False,
                reason=f"Persisted module {persisted_module_id!r} does not match active module {self.module_id!r}.",
            )
        return ResumeValidationResult(is_resumable=True)

    # Future-facing methods. These will acquire real behavior in later phases.
    def initialize_session(self, **kwargs: Any) -> Mapping[str, Any]:
        from app.modules.aims.services.session_initializer import (
            initialize_session as initialize_aims_session,
        )

        raw = initialize_aims_session(
            kwargs["body"],
            memory_store=kwargs["memory_store"],
            memory_enabled=bool(kwargs["memory_enabled"]),
            logger=kwargs["logger"],
            module_id=self.module_id,
        )
        artifact = None
        if isinstance(raw.get("initialCard"), str) and raw["initialCard"].strip():
            artifact = StartupArtifact(
                kind="scenario_card",
                title="Scenario Briefing",
                content=raw["initialCard"],
            )
        payload = SessionBootstrapPayload(
            module_id=self.module_id,
            session_id=str(raw["sessionId"]),
            already_active=bool(raw.get("alreadyActive", False)),
            participant_context={
                "character": raw.get("character"),
                "scene": raw.get("scene"),
            },
            module_state={
                "persona": raw.get("persona"),
                "personaId": raw.get("personaId"),
                "personaName": raw.get("personaName"),
            },
            artifacts=(artifact,) if artifact is not None else (),
        )
        return serialize_session_bootstrap_payload(payload)

    def build_startup_payload(self, **kwargs: Any) -> Mapping[str, Any]:
        raise NotImplementedError("Startup payload is not routed through TrainingModule yet.")

    def build_startup_artifacts(self, **kwargs: Any) -> list[Mapping[str, Any]]:
        raise NotImplementedError("Startup artifacts are not routed through TrainingModule yet.")

    async def handle_turn(self, **kwargs: Any) -> Mapping[str, Any]:
        req = kwargs["req"]
        body = kwargs["body"]
        ctx = kwargs["ctx"]
        memory_store = kwargs["memory_store"]
        vertex_config = dict(kwargs["vertex_config"])
        memory_config = dict(kwargs["memory_config"])
        aims_config = dict(kwargs["aims_config"])
        logger = kwargs["logger"]

        coaching_enabled = bool(aims_config.get("enabled", False))
        force_default = bool(aims_config.get("force_default", False))
        should_use_coaching = coaching_enabled and (bool(getattr(body, "coach", False)) or force_default)

        if should_use_coaching:
            from app.modules.aims.services.aims_coaching_handler import AimsCoachingHandler

            logger.debug("Module dispatch: module=%s route=coaching", self.module_id)
            handler = AimsCoachingHandler(
                memory_store=memory_store,
                vertex_config=vertex_config,
                memory_config=memory_config,
                logger=logger,
            )
            result = cast(Mapping[str, Any], await handler.handle(req, body, ctx))
            return {"_dispatch_path": "coaching", **result}

        from app.modules.aims.services.legacy_chat_handler import LegacyChatHandler

        logger.debug("Module dispatch: module=%s route=legacy", self.module_id)
        legacy_handler = LegacyChatHandler(
            memory_store=memory_store,
            vertex_config=vertex_config,
            memory_config=memory_config,
            logger=logger,
        )
        result = cast(Mapping[str, Any], await legacy_handler.handle(req, body, ctx))
        return {"_dispatch_path": "legacy", **result}

    def format_module_response(self, **kwargs: Any) -> Mapping[str, Any]:
        result = kwargs.get("result") or {}
        session_id = kwargs.get("session_id")

        envelope = ModuleResponseEnvelope(
            module_id=self.module_id,
            reply=str(result.get("reply") or ""),
            model=str(result.get("model") or ""),
            latency_ms=int(result.get("latency_ms") or 0),
            session=dict(result.get("session") or {}),
            feedback=dict(result.get("coaching") or {}) if result.get("coaching") is not None else None,
            summary=dict(result.get("summary") or {}) if result.get("summary") is not None else None,
            completion=(
                game_over_completion(dict(result["coach_post"]))
                if result.get("coach_post")
                else None
            ),
        )
        compatibility: dict[str, Any] = {}
        if envelope.feedback is not None:
            compatibility["coaching"] = dict(envelope.feedback)
        if result.get("coach_post"):
            compatibility["coachPost"] = result["coach_post"]
        return serialize_response_envelope(envelope, session_id=session_id, compatibility_overrides=compatibility)

    def build_system_instruction(self, **kwargs: Any) -> str | None:
        raise NotImplementedError("Prompt construction is not routed through TrainingModule yet.")

    def build_history_projection(self, **kwargs: Any) -> Mapping[str, Any]:
        raise NotImplementedError("History projection is not routed through TrainingModule yet.")

    @staticmethod
    async def build_summary(**kwargs: Any) -> Mapping[str, Any]:
        from app.modules.aims.services.summary_service import build_summary as build_aims_summary

        return await build_aims_summary(
            session_id=kwargs.get("session_id"),
            analysis=bool(kwargs.get("analysis", False)),
            memory_store=kwargs["memory_store"],
            memory_enabled=bool(kwargs["memory_enabled"]),
            settings=kwargs["settings"],
            logger=kwargs["logger"],
            app_state=kwargs["app_state"],
            vertex_client_cls=kwargs["vertex_client_cls"],
        )

    @staticmethod
    def build_archive_payload(**kwargs: Any) -> Mapping[str, Any] | None:
        result = kwargs.get("result") or {}
        ctx = kwargs["ctx"]
        session_service = kwargs["session_service"]
        memory_store = kwargs["memory_store"]

        coach_post = result.get("coach_post")
        if not coach_post:
            return None

        mem = session_service.get_mem(ctx.session_id)
        user_id = ctx.user_info.get("identifier") if ctx.user_info else None
        if not user_id:
            user_id = "anonymous"

        mem["session_ended"] = time.time()
        memory_store[ctx.session_id] = mem
        return {
            **mem,
            "session_id": ctx.session_id,
            "user_id": user_id,
            "game_over": True,
            "coach_post": coach_post,
            "exported_via": "endgame",
        }

    def build_archive_envelope(self, **kwargs: Any) -> ModuleArchiveEnvelope:
        session_id = str(kwargs["session_id"])
        user_id = str(kwargs["user_id"])
        data = dict(kwargs["data"] or {})
        git_hash = str(kwargs.get("git_hash") or "unknown")
        settings = kwargs["settings"]

        started_at = data.get("session_started")
        ended_at = data.get("session_ended") or data.get("updated")
        duration = None
        if started_at is not None and ended_at is not None:
            try:
                duration = round(float(ended_at) - float(started_at), 2)
            except (TypeError, ValueError):
                duration = None

        metadata = {
            "sessionId": session_id,
            "userId": user_id,
            "moduleId": self.module_id,
            "gitHash": git_hash,
            "timestamps": {
                "startedAt": self._iso(started_at),
                "endedAt": self._iso(ended_at),
                "durationSeconds": duration,
            },
            "outcome": {
                "isGameOver": data.get("game_over", False),
                "exitContext": "bug_report" if "error_report" in data else "completion" if data.get("game_over") else "abandoned",
                "report": {
                    "reason": data.get("error_report"),
                    "reportedAt": data.get("reported_at"),
                }
                if "error_report" in data
                else None,
            },
        }
        participant_context = {
            "personaId": (data.get("persona") or {}).get("id") if isinstance(data.get("persona"), dict) else None,
            "personaName": (data.get("persona") or {}).get("name") if isinstance(data.get("persona"), dict) else None,
            "character": data.get("character"),
            "scene": data.get("scene"),
        }
        analytics = {
            "totalTurns": (data.get("aims") or {}).get("totalTurns"),
            "perStepCounts": (data.get("aims") or {}).get("perStepCounts"),
            "runningAverage": (data.get("aims") or {}).get("runningAverage"),
        }
        payload = {
            "analytics": analytics,
            "conversationState": data.get("aims_state"),
            "summary": data.get("coach_post"),
        }
        compatibility = ArchiveCompatibilityPayload(
            config={
                "persona": {
                    "id": participant_context.get("personaId"),
                    "name": participant_context.get("personaName"),
                    "character": participant_context.get("character"),
                    "scene": participant_context.get("scene"),
                },
                "model": {
                    "id": settings.MODEL_ID,
                    "region": settings.REGION,
                },
            },
            analytics={
                "aims": analytics,
                "conversationState": data.get("aims_state"),
                "summary": data.get("coach_post"),
            },
        )
        return ModuleArchiveEnvelope(
            module_id=self.module_id,
            archive_schema_version=self.manifest.archive_schema_version,
            metadata=metadata,
            environment={
                "appEnv": settings.APP_ENV,
                "gcsObjectPrefix": settings.gcs_object_prefix,
            },
            transcript=tuple(self._build_transcript(data.get("full_history") or [])),
            participant_context=participant_context,
            payload=payload,
            compatibility=compatibility,
        )

    def build_jailbreak_fallback(self, **kwargs: Any) -> str:
        raise NotImplementedError("Fallback copy is not routed through TrainingModule yet.")

    @staticmethod
    def _iso(ts: Any) -> str | None:
        if ts is None:
            return None
        try:
            return datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc).isoformat().replace("+00:00", "Z")
        except (TypeError, ValueError):
            return None

    def _build_transcript(self, full_history: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
        transcript: list[dict[str, Any]] = []
        current_turn = 0
        for entry in full_history:
            role = str(entry.get("role") or ROLE_ASSISTANT).lower().strip()
            if role == ROLE_SYSTEM:
                transcript.append(
                    {
                        "turn": current_turn,
                        "role": ROLE_SYSTEM,
                        "content": entry.get("content"),
                        "timestamp": self._iso(entry.get("time")),
                    }
                )
            elif role == ROLE_USER:
                current_turn += 1
                transcript.append(
                    {
                        "turn": current_turn,
                        "role": ROLE_USER,
                        "content": entry.get("content"),
                        "timestamp": self._iso(entry.get("time")),
                    }
                )
            elif role == ROLE_ASSISTANT:
                transcript.append(
                    {
                        "turn": current_turn,
                        "role": ROLE_ASSISTANT,
                        "content": entry.get("content"),
                        "timestamp": self._iso(entry.get("time")),
                        "coaching": None,
                    }
                )
            elif role == ROLE_COACH:
                coaching_data = entry.get("coaching_data")
                coaching = None
                if coaching_data:
                    coaching = {**coaching_data, "timestamp": self._iso(entry.get("time"))}
                transcript.append(
                    {
                        "turn": current_turn,
                        "role": ROLE_COACH,
                        "content": entry.get("content"),
                        "timestamp": self._iso(entry.get("time")),
                        "coaching": coaching,
                    }
                )
        return transcript


def create_aims_training_module(*, settings: Any) -> AimsTrainingModule:
    chat_profile_name = "AIMSBot"
    loading_text = "Loading your scenario..."
    if hasattr(settings, "module_redis_key_prefix"):
        storage_prefix = settings.module_redis_key_prefix("aims")
    else:
        storage_prefix = getattr(settings, "redis_key_prefix", "aims:local:session:")
    manifest = ModuleManifest(
        id="aims",
        display_name="AIMS",
        chat_profile_name=chat_profile_name,
        archive_schema_version="aims-v1",
        storage_prefix=storage_prefix,
            dialogue_roles=DialogueRoles(
                participant_roles=(ROLE_USER, ROLE_ASSISTANT),
                feedback_roles=(ROLE_COACH,),
                metadata_roles=(ROLE_SYSTEM,),
                counted_roles=(ROLE_USER, ROLE_ASSISTANT),
                user_roles=(ROLE_USER,),
                counterpart_roles=(ROLE_ASSISTANT,),
                display_names={
                    ROLE_USER: "Doctor",
                    ROLE_ASSISTANT: "Assistant",
                    ROLE_COACH: "Coach",
                    ROLE_SYSTEM: "System",
                },
            ),
        supports_intro=True,
        supports_feedback=True,
        supports_summary=True,
        frontend_js_bundles=(
            "/public/js/modules/aims/module-ui.js",
        ),
        frontend_css="/public/aimsbot.css",
        branding=BrandingSpec(
            app_title="AIMSBot",
            avatar_name=chat_profile_name,
            logo_asset="/public/logo_light.png",
            loading_text=loading_text,
        ),
    )
    return AimsTrainingModule(manifest=manifest)
