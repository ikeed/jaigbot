from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

from app.core.archive_types import ArchiveCompatibilityPayload, ModuleArchiveEnvelope
from app.core.module_types import BrandingSpec, DialogueRoles, ModuleManifest, ResumeValidationResult
from app.core.response_serialization import serialize_response_envelope
from app.core.response_types import ModuleResponseEnvelope
from app.core.session_serialization import serialize_session_bootstrap_payload
from app.core.session_types import SessionBootstrapPayload, StartupArtifact


@dataclass(frozen=True)
class InterviewTrainingModule:
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

    def initialize_session(self, **kwargs: Any) -> Mapping[str, Any]:
        body = kwargs["body"]
        memory_store = kwargs["memory_store"]
        memory_enabled = bool(kwargs["memory_enabled"])

        session_id = str(body.sessionId)
        scene = body.scene or "Practice a behavioral interview with a hiring manager."
        character = body.character or (
            "You are the hiring manager in a structured job interview. Ask concise follow-up questions "
            "about outcomes, tradeoffs, and reflection."
        )
        initial_card = body.initialCard or (
            "Interview Setup\n"
            "Role: Hiring Manager\n"
            "Focus: Ask the candidate to explain one concrete project using outcomes and reflection."
        )

        if memory_enabled:
            now = time.time()
            mem = memory_store.get(session_id) or {
                "history": [],
                "full_history": [],
                "session_started": now,
            }
            history = mem.get("history")
            if not isinstance(history, list):
                history = []
                mem["history"] = history
            full_history = mem.get("full_history")
            if not isinstance(full_history, list):
                full_history = []
                mem["full_history"] = full_history
            if not history:
                history.append({"role": "system", "content": initial_card})
                full_history.append({"role": "system", "content": initial_card, "time": now})
            mem["character"] = character
            mem["scene"] = scene
            mem["module_id"] = self.module_id
            mem["user_info"] = body.userInfo
            mem["updated"] = now
            memory_store[session_id] = mem

        payload = SessionBootstrapPayload(
            module_id=self.module_id,
            session_id=session_id,
            participant_context={"character": character, "scene": scene},
            module_state={
                "persona": {"name": "Hiring Manager"},
                "personaId": "hiring-manager",
                "personaName": "Hiring Manager",
            },
            artifacts=(
                StartupArtifact(
                    kind="interview_brief",
                    title="Interview Setup",
                    content=initial_card,
                    metadata={"audience": "candidate"},
                ),
            ),
            transport_metadata={"artifactKind": "interview_brief"},
        )
        return serialize_session_bootstrap_payload(payload)

    def build_startup_payload(self, **kwargs: Any) -> Mapping[str, Any]:
        raise NotImplementedError("Startup payload is not routed through TrainingModule yet.")

    def build_startup_artifacts(self, **kwargs: Any) -> list[Mapping[str, Any]]:
        raise NotImplementedError("Startup artifacts are not routed through TrainingModule yet.")

    async def handle_turn(self, **kwargs: Any) -> Mapping[str, Any]:
        body = kwargs["body"]
        ctx = kwargs["ctx"]
        memory_store = kwargs["memory_store"]

        reply = "Tell me more about the impact you had and what you learned."
        mem = memory_store.get(ctx.session_id)
        if isinstance(mem, dict):
            history = mem.get("history")
            if isinstance(history, list):
                history.append({"role": "candidate", "content": body.message})
                history.append({"role": "interviewer", "content": reply})
            full_history = mem.get("full_history")
            if isinstance(full_history, list):
                now = time.time()
                full_history.append({"role": "candidate", "content": body.message, "time": now})
                full_history.append({"role": "interviewer", "content": reply, "time": now})
            mem["updated"] = time.time()
            mem["module_id"] = self.module_id
            memory_store[ctx.session_id] = mem

        return {
            "reply": reply,
            "model": "interview-stub",
            "latency_ms": 0,
            "session": {"mode": "interview"},
        }

    def format_module_response(self, **kwargs: Any) -> Mapping[str, Any]:
        result = kwargs.get("result") or {}
        envelope = ModuleResponseEnvelope(
            module_id=self.module_id,
            reply=str(result.get("reply") or ""),
            model=str(result.get("model") or "interview-stub"),
            latency_ms=int(result.get("latency_ms") or 0),
            session=dict(result.get("session") or {}),
            artifacts=(
                {"kind": "interview_prompt", "title": "Follow-up", "content": "Use a STAR-style answer if helpful."},
            ),
        )
        return serialize_response_envelope(envelope, session_id=kwargs.get("session_id"))

    def build_system_instruction(self, **kwargs: Any) -> str | None:
        raise NotImplementedError("Prompt construction is not routed through TrainingModule yet.")

    def build_history_projection(self, **kwargs: Any) -> Mapping[str, Any]:
        raise NotImplementedError("History projection is not routed through TrainingModule yet.")

    async def build_summary(self, **kwargs: Any) -> Mapping[str, Any]:
        return {"moduleId": self.module_id, "supported": False}

    def build_archive_payload(self, **kwargs: Any) -> Mapping[str, Any] | None:
        return None

    def build_archive_envelope(self, **kwargs: Any) -> ModuleArchiveEnvelope:
        session_id = str(kwargs["session_id"])
        user_id = str(kwargs["user_id"])
        data = dict(kwargs["data"] or {})
        transcript = tuple(dict(entry) for entry in (data.get("history") or []))
        return ModuleArchiveEnvelope(
            module_id=self.module_id,
            archive_schema_version=self.manifest.archive_schema_version,
            metadata={"sessionId": session_id, "userId": user_id, "moduleId": self.module_id},
            environment={"appEnv": getattr(kwargs["settings"], "APP_ENV", "local")},
            transcript=transcript,
            participant_context={"personaName": "Hiring Manager"},
            payload={"mode": "interview"},
            compatibility=ArchiveCompatibilityPayload(),
        )

    def build_jailbreak_fallback(self, **kwargs: Any) -> str:
        return "Let's stay focused on the interview scenario."


def create_interview_training_module(*, settings: Any) -> InterviewTrainingModule:
    if hasattr(settings, "module_redis_key_prefix"):
        storage_prefix = settings.module_redis_key_prefix("interview")
    else:
        app_env = getattr(settings, "APP_ENV", "local")
        storage_prefix = f"interview:{app_env}:session:"

    return InterviewTrainingModule(
        manifest=ModuleManifest(
            id="interview",
            display_name="Interview Practice",
            chat_profile_name="Interview Coach",
            archive_schema_version="interview-v1",
            storage_prefix=storage_prefix,
            dialogue_roles=DialogueRoles(
                participant_roles=("candidate", "interviewer"),
                feedback_roles=("observer",),
                metadata_roles=("system",),
                counted_roles=("candidate", "interviewer"),
                user_roles=("candidate",),
                counterpart_roles=("interviewer",),
                display_names={
                    "candidate": "Candidate",
                    "interviewer": "Interviewer",
                    "observer": "Observer",
                    "system": "System",
                },
            ),
            supports_intro=False,
            supports_feedback=False,
            supports_summary=False,
            frontend_js_bundles=("/public/js/modules/interview/module-ui.js",),
            frontend_css="/public/aimsbot.css",
            branding=BrandingSpec(
                app_title="Interview Practice",
                avatar_name="Interviewer",
                loading_text="Loading your interview...",
            ),
        )
    )
