"""
AIMS coaching path handler.

This service handles the full coaching flow:
1. Load AIMS mapping and evaluate deterministic classification
2. Perform LLM-based classification with fallbacks
3. Apply vaccine relevance gating 
4. Update AIMS state and metrics
5. Generate patient reply with safety checks
6. Handle end-game detection and coach posts

Behavior-preserving extraction from the massive coaching section in app.main.chat().
"""
from __future__ import annotations

import os
import time
import uuid
from types import SimpleNamespace
from typing import Any, Dict, Optional

from fastapi import Request

from app.chat_roles import ROLE_USER, ROLE_ASSISTANT
from app.config import settings
from app.constants import (
    KEY_AIMS_STATE,
    KEY_FULL_HISTORY,
    KEY_COACH_POST,
    KEY_GAME_OVER,
    PHASE_PRE_ANNOUNCE,
    SESSION_HISTORY,
    KEY_UPDATED,
    SESSION_CHARACTER,
    SESSION_SCENE,
    DEFAULT_MODEL_FLASH
)
from app.models import ChatRequest
from app.modules.aims.engine import load_mapping
from app.modules.aims.services.aims_feedback_service import AimsFeedbackService
from app.modules.aims.services.aims_handler_config import AimsMemoryConfig, AimsVertexConfig
from app.modules.aims.services.aims_metrics_service import AimsMetricsService
from app.modules.aims.services.classifier_service import ClassifierService
from app.modules.aims.services.patient_reply_service import PatientReplyService
from app.modules.aims.services.summary_service import build_summary_analysis_bullets
from app.services.chat_context import ChatContext
from app.services.chat_helpers import strip_appointment_headers
from app.services.clinician_identity import clinician_display_name_from_user_info
from app.modules.aims.services.aims_dependencies import (
    AimsEndgameDependency,
    AimsFeedbackDependency,
    AimsMetricsDependency,
    AimsStateDependency,
    AimsTelemetryDependency,
    AimsTurnCoordinatorDependency,
    ClassifierDependency,
    CoachFeedbackHistoryDependency,
    PatientReplyDependency,
)
from app.modules.aims.services.aims_endgame_service import AimsEndgameService
from app.modules.aims.services.aims_state_service import AimsStateService
from app.modules.aims.services.aims_turn_telemetry import AimsTurnTelemetry
from app.modules.aims.services.aims_turn_coordinator import AimsTurnCoordinator
from app.modules.aims.services.coach_feedback_history_service import CoachFeedbackHistoryService
from app.modules.aims.services.coach_post import (
    VaccineRelevanceGate,
    AimsPostProcessor,
)
from app.services.vertex_helpers import (
    avertex_call_with_fallback_json,
    get_last_model_used
)
from app.vertex import VertexClient


class AimsCoachingHandler:
    """Handles the full AIMS coaching flow."""
    
    _TOPICAL_CUES = AimsStateService.TOPICAL_CUES

    @staticmethod
    def _build_reply_concern_state_section(state: dict[str, Any] | None) -> str:
        concerns = (state or {}).get("parent_concerns") or []
        if not concerns:
            return "No tracked vaccine concerns yet."

        open_topics: list[str] = []
        resolved_topics: list[str] = []
        for concern in concerns:
            topic = str(
                concern.get("canonical_label")
                or concern.get("summary")
                or concern.get("topic")
                or "unspecified concern"
            ).strip()
            if not topic:
                continue
            if concern.get("is_secured"):
                if topic not in resolved_topics:
                    resolved_topics.append(topic)
            else:
                if topic not in open_topics:
                    open_topics.append(topic)

        if not open_topics and resolved_topics:
            return (
                "Open concerns: none. "
                f"Resolved concerns: {', '.join(resolved_topics)}. "
                "Do not reopen resolved concerns as if unanswered."
            )
        if open_topics and resolved_topics:
            return (
                f"Open concerns: {', '.join(open_topics)}. "
                f"Resolved concerns: {', '.join(resolved_topics)}. "
                "Focus on open concerns; do not reopen resolved concerns as if unanswered."
            )
        return f"Open concerns: {', '.join(open_topics)}."
    
    def __init__(
        self,
        *,
        memory_store: Any,
        vertex_config: dict[str, Any],
        memory_config: dict[str, Any],
        logger: Any,
        classifier_service: ClassifierDependency | None = None,
        patient_reply_service: PatientReplyDependency | None = None,
        state_service: AimsStateDependency | None = None,
        feedback_service: AimsFeedbackDependency | None = None,
        metrics_service: AimsMetricsDependency | None = None,
        coach_feedback_history_service: CoachFeedbackHistoryDependency | None = None,
        endgame_service: AimsEndgameDependency | None = None,
        telemetry: AimsTelemetryDependency | None = None,
        turn_coordinator: AimsTurnCoordinatorDependency | None = None,
    ):
        self.memory_store = memory_store
        self.vertex_config = AimsVertexConfig.from_mapping(vertex_config)
        self.memory_config = AimsMemoryConfig.from_mapping(memory_config)
        self.logger = logger
        
        # Extract frequently used config
        self.project_id = self.vertex_config.project_id
        self.region = self.vertex_config.region
        self.vertex_location = self.vertex_config.vertex_location
        self.model_id = self.vertex_config.model_id
        self.model_fallbacks = self.vertex_config.model_fallbacks
        self.temperature = self.vertex_config.temperature
        self.max_tokens = self.vertex_config.max_tokens
        
        # Per-call tuning (env-configurable) for latency/cost-sensitive JSON tasks
        self.classify_temperature = float(os.getenv("AIMS_CLASSIFY_TEMPERATURE", "0.1"))
        self.classify_max_tokens = int(os.getenv("AIMS_CLASSIFY_MAX_TOKENS", "4096"))
        self.endgame_temperature = float(os.getenv("AIMS_ENDGAME_TEMPERATURE", "0.1"))
        self.endgame_max_tokens = int(os.getenv("AIMS_ENDGAME_MAX_TOKENS", "192"))
        self.classify_budget_s = float(os.getenv("AIMS_CLASSIFY_BUDGET_S", "30.0"))

        # Allow tests to monkeypatch the client via app.main.VertexClient
        self.client_cls = self.vertex_config.client_cls or VertexClient
        
        self.memory_enabled = self.memory_config.enabled
        self.memory_max_turns = self.memory_config.max_turns
        self.summary_app_state = SimpleNamespace()
        
        self.classifier_service = classifier_service or ClassifierService(
            project_id=self.project_id,
            location=self.vertex_location,
            model_id=self.model_id,
            logger=self.logger,
            temperature=self.classify_temperature,
            max_tokens=self.classify_max_tokens,
            client_cls=self.client_cls,
        )
        self.patient_reply_service = patient_reply_service or PatientReplyService(
            model_json_caller=self._call_vertex_json,
            logger=self.logger,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        self.metrics_service = metrics_service or AimsMetricsService(logger=self.logger)
        self.state_service = state_service or AimsStateService(logger=self.logger)
        self.feedback_service = feedback_service or AimsFeedbackService(
            project_id=self.project_id,
            region=self.vertex_location,
            model_id=self.model_id,
            model_fallbacks=self.model_fallbacks,
            temperature=min(self.temperature, 0.2),
            max_tokens=min(self.max_tokens, 384),
            client_cls=self.client_cls,
            logger=self.logger,
        )
        self.coach_feedback_history_service = (
            coach_feedback_history_service
            or CoachFeedbackHistoryService(logger=self.logger)
        )
        self.endgame_service = endgame_service or AimsEndgameService(
            logger=self.logger,
            classifier_service_getter=lambda: self.classifier_service,
            summary_bullets_builder=lambda mem: build_summary_analysis_bullets(
                mem=mem,
                settings=settings,
                logger=self.logger,
                app_state=self.summary_app_state,
                vertex_client_cls=self.client_cls,
            ),
        )
        self.telemetry = telemetry or AimsTurnTelemetry(
            logger=self.logger,
            model_id=self.model_id,
        )
        self.turn_coordinator = turn_coordinator or AimsTurnCoordinator(
            classifier_service=self.classifier_service,
            patient_reply_service=self.patient_reply_service,
            classify_budget_s=self.classify_budget_s,
            logger=self.logger,
        )
    
    async def handle(
        self, req: Request, body: ChatRequest, ctx: ChatContext
    ) -> Dict[str, Any]:
        """Handle the full AIMS coaching flow."""
        started = time.time()

        # Helper to get request id for correlation
        def _req_id() -> str:
            try:
                return (
                    req.headers.get("x-cloud-trace-context")
                    or req.headers.get("x-request-id")
                    or str(uuid.uuid4())
                )
            except Exception as exc:
                self.logger.warning("Failed to get request correlation id: %s", exc)
                return str(uuid.uuid4())

        request_id = _req_id()

        # Load AIMS mapping (cached at app level)
        mapping = await self._load_aims_mapping()
        
        # Step 1 & 2: Unified Classification (LLM with deterministic fallback)
        cls_start = time.time()
        reply_start = time.time()
        self._emit_telemetry(
            "classify_begin",
            session_id=ctx.session_id,
            user_info=ctx.user_info,
            request_id=request_id,
        )
        self._emit_telemetry(
            "reply_begin",
            session_id=ctx.session_id,
            user_info=ctx.user_info,
            request_id=request_id,
        )

        # Load session memory once for the entire request; all sub-methods
        # mutate this dict in place and we write back once at the end.
        mem = self._load_mem(ctx.session_id)
        prior_state = mem.get(KEY_AIMS_STATE) or {} if mem else {}
        prior_announced = bool(prior_state.get("announced", False))
        prior_phase = prior_state.get("phase", PHASE_PRE_ANNOUNCE)
        concern_state_section = self._build_reply_concern_state_section(prior_state)

        turn = await self.turn_coordinator.run(
            clinician_message=body.message,
            person_last=ctx.person_last,
            history=ctx.mem.get(SESSION_HISTORY, []) if ctx.mem else [],
            prior_announced=prior_announced,
            prior_phase=prior_phase,
            mapping=mapping,
            context_turns=settings.AIMS_CLASSIFY_CONTEXT_TURNS,
            max_concerns=settings.AIMS_CLASSIFY_MAX_CONCERNS,
            inquired_concerns_list=[
                c["topic"] for c in (prior_state or {}).get("parent_concerns", [])
            ],
            mirrored_concerns_list=[
                c["topic"]
                for c in (prior_state or {}).get("parent_concerns", [])
                if c.get("is_mirrored")
            ],
            history_text=ctx.history_text,
            session_id=ctx.session_id,
            character=ctx.effective_character,
            scene=ctx.effective_scene,
            clinician_name=clinician_display_name_from_user_info(ctx.user_info),
            concern_state_section=concern_state_section,
        )
        cls_payload = turn.cls_payload
        is_small_talk = turn.is_small_talk
        classification_result = turn.classification_result
        reply_payload = turn.reply_payload

        # Apply post-processors to BOTH LLM and fallback results
        # Vaccine relevance gate
        mem = ctx.mem or {}
        aims_state = mem.get(KEY_AIMS_STATE, {}) or {}
        parent_concerns = aims_state.get("parent_concerns", [])
        recent_concerns_texts = [
            str(c.get("summary") or c.get("desc") or " ".join(c.get("evidence") or []))
            for c in parent_concerns
        ] if parent_concerns else []
        
        cls_payload = VaccineRelevanceGate.gate(
            cls_payload=cls_payload,
            clinician_text=body.message,
            person_last=ctx.person_last,
            parent_recent_concerns=recent_concerns_texts,
            prior_announced=prior_announced
        )
        
        # Only apply small-talk override when no AIMS step was detected.
        # If an AIMS step is present (e.g. from _apply_overrides Announce correction),
        # the LLM's small-talk flag must not clobber it.
        if is_small_talk and not cls_payload.get("step"):
            cls_payload["step"] = None
            cls_payload["score"] = 0
            cls_payload["reasons"] = (cls_payload.get("reasons") or []) + ["LLM flagged as small talk"]
            
        # Legacy AimsPostProcessor (score normalization, score capping)
        cls_payload = AimsPostProcessor.post_process(cls_payload, body.message)

        # Populate current phase for UI transparency
        cls_payload["phase"] = aims_state.get("phase", PHASE_PRE_ANNOUNCE)
        
        # Try to snapshot model used for classification (may be approximate if overwritten by parallel call)
        try:
            model_used_cls = get_last_model_used() or self.model_id
        except Exception as e:
            self.logger.debug("Failed to snapshot model used: %s", e)
            model_used_cls = self.model_id
        self._emit_telemetry(
            "classify_end",
            session_id=ctx.session_id,
            request_id=request_id,
            started=cls_start,
            model_used=model_used_cls,
            step=cls_payload.get("step"),
            score=cls_payload.get("score"),
        )

        # Step 3: Update AIMS state and provide coaching guidance (after classification completes)
        llm_topic = classification_result.person_topic if classification_result else None
        self.state_service.update(
            mem,
            cls_payload,
            body.message,
            ctx.person_last,
            llm_topic,
        )

        if turn.was_fallback:
            try:
                cls_payload = await self.feedback_service.refine_fallback_feedback(
                    cls_payload=cls_payload,
                    clinician_message=body.message,
                    person_last=ctx.person_last,
                    history_text=ctx.history_text,
                    state=mem.get(KEY_AIMS_STATE) if mem else None,
                    character=ctx.effective_character,
                    person_topic=classification_result.person_topic if classification_result else None,
                )
            except Exception as e:
                self.logger.debug("AIMS feedback refinement failed: %s", e)

        # Step 4: Persist AIMS metrics (after state update)
        try:
            self.metrics_service.persist(mem, cls_payload)
        except Exception as e:
            self.logger.debug("AIMS metrics persist failed: %s", e)

        # Record the clinician turn before any coaching note so replay keeps
        # the same order the live UI showed: user -> coach -> assistant.
        self._append_user_history(mem, body.message)

        # Persist a compact coaching note before assistant reply so replay keeps
        # the same order the live UI showed: user -> coach -> assistant.
        self.coach_feedback_history_service.append(
            mem=mem,
            memory_enabled=self.memory_enabled,
            session_id=ctx.session_id,
            cls_payload=cls_payload,
            reply_payload=reply_payload,
        )

        # Calculate reply duration from its previously completed task
        try:
            model_used_reply = get_last_model_used() or self.model_id
        except Exception as e:
            self.logger.warning("Failed to snapshot model used for reply: %s", e)
            model_used_reply = self.model_id
        self._emit_telemetry(
            "reply_end",
            session_id=ctx.session_id,
            request_id=request_id,
            started=reply_start,
            model_used=model_used_reply,
            text_len=len((reply_payload.get("patient_reply") or "").strip()),
        )

        self._strip_initial_reply_headers(reply_payload, ctx.person_last)
        
        # Step 6: Update conversation history
        self._append_assistant_history(mem, reply_payload.get("patient_reply", ""))
        
        # Step 7: Build session metrics
        try:
            session_obj = self.metrics_service.build_summary(mem)
        except Exception as e:
            self.logger.debug("AIMS metrics summary failed: %s", e)
            session_obj = {}
        
        # Step 8: Check for end-game scenarios
        coach_post = await self.endgame_service.check(mem, reply_payload, session_obj, ctx.session_id)
        
        # Save coach_post to memory if it exists, so it can be archived
        if coach_post and mem is not None:
            mem[KEY_COACH_POST] = coach_post
            mem[KEY_GAME_OVER] = True
        
        # Single write-back of all accumulated mutations
        if mem is not None and self.memory_enabled and ctx.session_id:
            mem[KEY_UPDATED] = time.time()
            self.memory_store[ctx.session_id] = mem
        
        # Calculate final latency
        latency_ms = int((time.time() - started) * 1000)
        
        # Log successful completion
        self._emit_telemetry(
            "turn_ok",
            latency_ms=latency_ms,
            session_id=ctx.session_id,
            user_info=ctx.user_info,
            step=cls_payload.get("step"),
            score=cls_payload.get("score"),
        )
        
        # Return structured result
        # Report the actual model used (considering fallbacks) when available
        try:
            model_used = get_last_model_used() or self.model_id
        except Exception as e:
            self.logger.warning("Failed to determine model used for response: %s", e)
            model_used = self.model_id

        result = {
            "reply": reply_payload.get("patient_reply", ""),
            "model": model_used,
            "latency_ms": latency_ms,
            "coaching": {
                "step": cls_payload.get("step"),
                "score": cls_payload.get("score"),
                # Strip internal guard/debug reasons before sending to client
                "reasons": self.coach_feedback_history_service.filter_user_facing_reasons(
                    cls_payload.get("reasons", []),
                    step=cls_payload.get("step"),
                ),
                "tips": cls_payload.get("tips", []),
                "step_feedback": [
                    sf if isinstance(sf, dict) else sf.model_dump()
                    for sf in (cls_payload.get("step_feedback") or [])
                ],
                "phase": cls_payload.get("phase"),
            },
            "session": session_obj,
        }
        
        if coach_post:
            result["coach_post"] = coach_post
        
        return result
    
    async def _load_aims_mapping(self) -> Dict[str, Any]:
        """Load and cache AIMS mapping via lru_cache on load_mapping()."""
        try:
            return load_mapping()
        except Exception as e:
            self.logger.warning("AIMS mapping failed to load: %s", e)
            return {}

    def _emit_telemetry(self, method_name: str, **kwargs: Any) -> None:
        """Emit non-critical telemetry without letting logging failures abort chat."""
        try:
            getattr(self.telemetry, method_name)(**kwargs)
        except Exception as e:
            self.logger.debug("AIMS telemetry %s failed: %s", method_name, e)

    def _strip_initial_reply_headers(
        self,
        reply_payload: Dict[str, Any],
        person_last: str,
    ) -> None:
        """Remove scenario headers from the first assistant reply.

        The UI already shows the scenario card for the initial turn, so we
        keep the assistant text focused on the actual reply content.
        """
        try:
            if (person_last or "").strip():
                return
            reply = reply_payload.get("patient_reply", "")
            reply_payload["patient_reply"] = strip_appointment_headers(reply)
        except Exception as e:
            self.logger.warning("Failed to strip appointment headers: %s", e)
    
    def _load_mem(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load session memory once. Returns None if memory is disabled."""
        if not (self.memory_enabled and session_id):
            return None
        mem = self.memory_store.get(session_id)
        if mem is None:
            mem = {
                SESSION_HISTORY: [], KEY_FULL_HISTORY: [], SESSION_CHARACTER: None,
                SESSION_SCENE: None, KEY_UPDATED: time.time(),
            }
        mem.setdefault(KEY_FULL_HISTORY, [])
        return mem

    def _append_user_history(self, mem: Optional[Dict[str, Any]], user_message: str) -> None:
        """Append a user message to history. Mutates mem in place."""
        if mem is None:
            return

        try:
            now = time.time()
            user_entry = {"role": ROLE_USER, "content": user_message}
            mem.setdefault(SESSION_HISTORY, []).append(user_entry)
            mem.setdefault(KEY_FULL_HISTORY, []).append({**user_entry, "time": now})
            mem[KEY_UPDATED] = now
        except Exception as e:
            self.logger.debug(f"User history append failed: {e}")

    def _append_assistant_history(self, mem: Optional[Dict[str, Any]], assistant_reply: str) -> None:
        """Append an assistant message to history. Mutates mem in place."""
        if mem is None:
            return

        try:
            now = time.time()
            asst_entry = {"role": ROLE_ASSISTANT, "content": assistant_reply}
            mem.setdefault(SESSION_HISTORY, []).append(asst_entry)
            mem.setdefault(KEY_FULL_HISTORY, []).append({**asst_entry, "time": now})
            mem[KEY_UPDATED] = now

            # Trim working history (coach-aware) after the full turn is present.
            from app.services.session_service import SessionService
            mem[SESSION_HISTORY] = SessionService.trim_history(mem[SESSION_HISTORY], self.memory_max_turns)

        except Exception as e:
            self.logger.debug(f"Assistant history append failed: {e}")
    
    def _primary_for_json(self, log_path: str) -> tuple[str, list[str]]:
        """Select primary and fallback models for JSON tasks based on call path.
        - coach_classify: Pro primary (better semantics), Flash as fallback(s)
        - otherwise (e.g., endgame_detect): Flash primary, Pro as fallback
        """
        lp = (log_path or "").lower()
        # Start with configured fallbacks, ensuring uniqueness and preserving order
        pro_primary = self.model_id
        try:
            cfg_fallbacks = [m for m in (self.model_fallbacks or []) if m]
        except Exception as e:
            self.logger.debug(f"Failed to resolve model fallbacks: {e}")
            cfg_fallbacks = []
        flash = DEFAULT_MODEL_FLASH
        if lp == "coach_classify":
            # Pro primary, ensure Flash is in fallbacks
            fb = [x for x in ([flash] + cfg_fallbacks) if x]
            return pro_primary, fb
        # Default: Flash primary, Pro then others as fallbacks
        fb = [x for x in ([pro_primary] + cfg_fallbacks) if x]
        return flash, fb

    async def _call_vertex_json(self, prompt: str, schema: dict, log_path: str, *, temperature: float | None = None, max_tokens: int | None = None) -> str:
        """Call Vertex for JSON generation with fallbacks (native async)."""
        primary, fb = self._primary_for_json(log_path)
        return await avertex_call_with_fallback_json(
            project=self.project_id,
            region=self.vertex_location,
            primary_model=primary,
            fallbacks=fb,
            temperature=(self.temperature if temperature is None else temperature),
            max_tokens=(self.max_tokens if max_tokens is None else max_tokens),
            prompt=prompt,
            system_instruction=None,
            schema=schema,
            log_path=log_path,
            logger=self.logger,
            client_cls=self.client_cls,
        )
