"""
AIMS coaching path handler.

This service handles the full coaching flow:
1. Load supporting AIMS mapping data
2. Perform LLM-based structured classification with model fallbacks
3. Apply vaccine relevance gating 
4. Update AIMS state and metrics
5. Generate patient reply with safety checks
6. Handle end-game detection and coach posts

Behavior-preserving extraction from the massive coaching section in app.main.chat().
"""
from __future__ import annotations

import time
import uuid
from types import SimpleNamespace
from typing import Any, Dict, Optional

from fastapi import Request

from app.aims_mapping_loader import load_mapping
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
from app.message_catalog import message
from app.models import ChatRequest
from app.services.aims_dependencies import (
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
from app.services.aims_endgame_service import AimsEndgameService
from app.services.aims_feedback_service import AimsFeedbackService
from app.services.aims_handler_config import AimsMemoryConfig, AimsVertexConfig
from app.services.aims_metrics_service import AimsMetricsService
from app.services.aims_state_service import AimsStateService
from app.services.aims_turn_coordinator import AimsTurnCoordinator
from app.services.aims_turn_telemetry import AimsTurnTelemetry
from app.services.chat_context import ChatContext
from app.services.chat_helpers import strip_appointment_headers
from app.services.classifier_service import ClassifierService
from app.services.clinician_identity import clinician_display_name_from_user_info
from app.services.coach_feedback_history_service import CoachFeedbackHistoryService
from app.services.coach_post import (
    VaccineRelevanceGate,
    AimsPostProcessor,
)
from app.services.coaching_tip_sanitizer import sanitize_coaching_tips
from app.services.patient_reply_service import PatientReplyService
from app.services.summary_service import build_summary_analysis_bullets
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
            return message("patient_reply.concern_state.none_tracked")

        undiscovered_topics: list[str] = []
        open_topics: list[str] = []
        resolved_topics: list[str] = []
        for concern in concerns:
            # An undiscovered checklist entry hasn't been touched by
            # _normalize_existing_concern yet, so its authored `desc` (from
            # personas.json) is still intact -- prefer that over the bare
            # topic slug for richer roleplay grounding on what to eventually
            # reveal. Once discovered, canonical_label/summary take over as
            # usual.
            is_undiscovered_checklist_entry = concern.get(
                "from_checklist"
            ) and not concern.get("is_discovered")
            if is_undiscovered_checklist_entry:
                label = str(
                    concern.get("desc") or concern.get("topic") or message(
                        "patient_reply.concern_state.unspecified"
                    )
                ).strip()
                if label and label not in undiscovered_topics:
                    undiscovered_topics.append(label)
                continue

            topic = str(
                concern.get("canonical_label")
                or concern.get("summary")
                or concern.get("topic")
                or message("patient_reply.concern_state.unspecified")
            ).strip()
            if not topic:
                continue
            if concern.get("is_secured"):
                if topic not in resolved_topics:
                    resolved_topics.append(topic)
            else:
                if topic not in open_topics:
                    open_topics.append(topic)

        if not open_topics and not resolved_topics and not undiscovered_topics:
            return message("patient_reply.concern_state.none_tracked")

        # The "open concerns: none" marker (see open_none_resolved) drives the
        # patient-reply fallback's resolved-tone acknowledgement -- it must
        # only fire when NOTHING remains, including nothing undiscovered.
        if not open_topics and not undiscovered_topics and resolved_topics:
            section = message(
                "patient_reply.concern_state.open_none_resolved",
                resolved=", ".join(resolved_topics),
            )
        elif not open_topics and resolved_topics:
            section = message(
                "patient_reply.concern_state.resolved_pending_more",
                resolved=", ".join(resolved_topics),
            )
        elif open_topics and resolved_topics:
            section = message(
                "patient_reply.concern_state.open_and_resolved",
                open=", ".join(open_topics),
                resolved=", ".join(resolved_topics),
            )
        elif open_topics:
            section = message("patient_reply.concern_state.open_only", open=", ".join(open_topics))
        else:
            section = message("patient_reply.concern_state.nothing_surfaced_yet")

        if undiscovered_topics:
            section = (
                f"{section} "
                + message(
                    "patient_reply.concern_state.undiscovered_present",
                    undiscovered=", ".join(undiscovered_topics),
                )
            )
        return section

    @staticmethod
    def _build_classify_checklist_context(state: dict[str, Any] | None) -> str:
        """Persona checklist topics + discovery state for the classify_turn prompt.

        Scoped to from_checklist=True entries only -- ad-hoc concerns aren't
        part of the persona's known checklist and would just be noise here.
        Naturally carries scenario-local topics (e.g. Georgina's
        age_appropriateness) alongside the shared PERSON_TOPIC_CATEGORIES
        ones, since it renders whatever the persona's checklist contains.

        Includes each concern's authored `desc`, not just its bare topic
        name -- the classifier only knows a topic's *canonical* meaning
        (e.g. "trust" = distrust of sources/institutions per
        PERSON_TOPIC_CATEGORIES) unless told otherwise. A persona's specific
        framing of that topic can diverge from the canonical definition (a
        persona's "trust" concern might really be phrased as an evidence
        demand), and without the desc the classifier has no way to recognize
        persona-specific language as matching that checklist entry --
        confirmed live: without this, one persona's two concerns were
        classified as the same topic every turn because their bare topic
        names both effectively meant "wants data" to the model with no
        further grounding.
        """
        concerns = [
            c for c in (state or {}).get("parent_concerns") or [] if c.get("from_checklist")
        ]
        if not concerns:
            return ""

        def _render(c: dict[str, Any]) -> str:
            status = "discovered" if c.get("is_discovered") else "not yet discovered"
            entry = f"{c.get('topic')} ({status})"
            desc = c.get("desc")
            return f"{entry} -- {desc}" if desc else entry

        return "; ".join(_render(c) for c in concerns)

    @staticmethod
    def _append_endgame_blocked_tip(cls_payload: dict[str, Any]) -> None:
        """Surface the escalated Important tip for an endgame-backstop block.

        code="endgame_undiscovered_concern" is registered in
        coaching_display.py's IMPORTANT_FEEDBACK_CODES so this renders as
        "Important", not "Tip".

        Branches on whether this turn's classification already used
        structured feedback (feedback_items/step_feedback), mirroring
        AimsStateService._apply_secure_guidance's prefer_structured_feedback
        pattern -- coaching_display.py's coaching_message_parts only renders
        the legacy `reasons`/`tips` fallback when there are NO feedback_items,
        so unconditionally appending here would silently swallow this turn's
        own reasons/tips whenever the classifier happened to omit the
        optional feedback_items field (a normal, non-error occurrence, not
        just the dormant heuristic-fallback path).
        """
        text = message("endgame.undiscovered_concern_tip")
        has_structured_feedback = bool(
            cls_payload.get("feedback_items") or cls_payload.get("step_feedback")
        )
        if has_structured_feedback:
            items = cls_payload.setdefault("feedback_items", [])
            if any(
                isinstance(item, dict) and item.get("code") == "endgame_undiscovered_concern"
                for item in items
            ):
                return
            items.append(
                {
                    "step": cls_payload.get("step"),
                    "tone": "improvement",
                    "code": "endgame_undiscovered_concern",
                    "text": text,
                }
            )
        else:
            # Legacy path: only coaching.tips[0] is ever displayed
            # (coaching_display.py), so insert at the front rather than
            # append -- this block is the most consequential thing to
            # surface for the turn.
            tips = list(cls_payload.get("tips") or [])
            if text not in tips:
                tips.insert(0, text)
            cls_payload["tips"] = tips

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
        self.classifier_model_id = self.vertex_config.classifier_model_id
        self.classifier_thinking_level = self.vertex_config.classifier_thinking_level
        self.classifier_thinking_budget = self.vertex_config.classifier_thinking_budget
        self.temperature = self.vertex_config.temperature
        self.max_tokens = self.vertex_config.max_tokens
        
        # Per-call tuning for latency/cost-sensitive JSON tasks. These arrive through the
        # injected config rather than being read from the environment here, so they are
        # typed, visible on /config, and overridable by tests without touching os.environ.
        # AIMS_ENDGAME_TEMPERATURE/AIMS_ENDGAME_MAX_TOKENS used to be read here and were
        # never consumed by anything — endgame detection runs through
        # ClassifierService.detect_endgame, which uses the classify values.
        self.classify_temperature = self.vertex_config.classify_temperature
        self.classify_max_tokens = self.vertex_config.classify_max_tokens
        self.classify_budget_s = self.vertex_config.classify_budget_s
        self.heuristic_fallback_enabled = self.vertex_config.heuristic_fallback_enabled
        # Unset means "track the main token budget, with a floor for a full patient turn".
        self.reply_max_tokens = (
            self.vertex_config.reply_max_tokens
            if self.vertex_config.reply_max_tokens is not None
            else max(self.max_tokens, 1536)
        )

        # Allow tests to monkeypatch the client via app.main.VertexClient
        self.client_cls = self.vertex_config.client_cls or VertexClient
        
        self.memory_enabled = self.memory_config.enabled
        self.memory_max_turns = self.memory_config.max_turns
        self.summary_app_state = SimpleNamespace()
        
        self.classifier_service = classifier_service or ClassifierService(
            project_id=self.project_id,
            location=self.vertex_location,
            model_id=self.classifier_model_id,
            logger=self.logger,
            temperature=self.classify_temperature,
            max_tokens=self.classify_max_tokens,
            client_cls=self.client_cls,
            heuristic_fallback_enabled=self.heuristic_fallback_enabled,
            thinking_level=self.classifier_thinking_level,
            thinking_budget=self.classifier_thinking_budget,
        )
        self.patient_reply_service = patient_reply_service or PatientReplyService(
            model_json_caller=self._call_vertex_json,
            logger=self.logger,
            temperature=self.temperature,
            max_tokens=self.reply_max_tokens,
        )
        self.metrics_service = metrics_service or AimsMetricsService(logger=self.logger)
        self.state_service = state_service or AimsStateService(
            logger=self.logger,
            heuristic_fallback_enabled=self.heuristic_fallback_enabled,
        )
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
            heuristic_fallback_enabled=self.heuristic_fallback_enabled,
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
            heuristic_fallback_enabled=self.heuristic_fallback_enabled,
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
        
        # Step 1 & 2: Unified Classification (LLM structured output; legacy
        # heuristic fallback only when explicitly enabled)
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
        checklist_context = self._build_classify_checklist_context(prior_state)

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
                c["topic"]
                for c in (prior_state or {}).get("parent_concerns", [])
                # Checklist entries are pre-seeded from turn one, before they've
                # actually been surfaced -- only list ones genuinely discovered
                # so far. Non-checklist (ad-hoc) entries have no is_discovered
                # key; they're only ever created from real evidence, so treat
                # a missing key as discovered.
                if c.get("is_discovered", True)
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
            checklist_context=checklist_context,
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
            prior_announced=prior_announced,
            semantic_is_vaccine_relevant=(
                classification_result.is_vaccine_relevant
                if classification_result
                else None
            ),
            allow_keyword_fallback=self.heuristic_fallback_enabled,
        )
        
        # Only apply small-talk override when no AIMS step was detected.
        # If an AIMS step is present (e.g. from _apply_overrides Announce correction),
        # the LLM's small-talk flag must not clobber it.
        if is_small_talk and not cls_payload.get("step"):
            cls_payload["step"] = None
            cls_payload["score"] = 0
            cls_payload["reasons"] = (cls_payload.get("reasons") or []) + [
                message("aims.small_talk_reason")
            ]
            
        # Legacy AimsPostProcessor (score normalization, score capping)
        cls_payload = AimsPostProcessor.post_process(
            cls_payload,
            body.message,
            allow_text_softening=self.heuristic_fallback_enabled,
        )

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
            semantic_contract={
                "observations": bool(cls_payload.get("observations")),
                "feedback_items": bool(cls_payload.get("feedback_items")),
                "person_events": bool(classification_result and classification_result.person_events),
                "resolution": bool(classification_result and classification_result.resolution),
            },
        )

        # Step 3: Update AIMS state and provide coaching guidance (after classification completes)
        llm_topic = classification_result.person_topic if classification_result else None
        self.state_service.update(
            mem,
            cls_payload,
            body.message,
            ctx.person_last,
            llm_topic,
            person_events=classification_result.person_events if classification_result else None,
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

        sanitize_coaching_tips(
            cls_payload,
            clinician_message=body.message,
            allow_text_rewrite=self.heuristic_fallback_enabled,
        )

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
        coach_post = await self.endgame_service.check(
            mem,
            reply_payload,
            session_obj,
            ctx.session_id,
        )

        # The endgame backstop (aims_endgame_service.py) blocked a would-be
        # closure because a checklist concern is still undiscovered -- it
        # can't return that fact through coach_post (check() must behave
        # like any other non-endgame turn), so it flags aims_state instead.
        # Note: this lands in the live turn's coaching.tips but not in the
        # coach_feedback_history_service note already appended above, since
        # that snapshot is taken before check() runs (it must stay between
        # the user/assistant history entries for replay ordering).
        if mem is not None and (mem.get(KEY_AIMS_STATE) or {}).get(
            "endgame_blocked_undiscovered"
        ):
            self._append_endgame_blocked_tip(cls_payload)

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

        coaching_payload = {
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
        }

        observations = cls_payload.get("observations")
        if isinstance(observations, dict):
            coaching_payload["observations"] = observations

        feedback_items = [
            item if isinstance(item, dict) else item.model_dump()
            for item in (cls_payload.get("feedback_items") or [])
            if isinstance(item, dict) or hasattr(item, "model_dump")
        ]
        if feedback_items:
            coaching_payload["feedback_items"] = feedback_items

        result = {
            "reply": reply_payload.get("patient_reply", ""),
            "model": model_used,
            "latency_ms": latency_ms,
            "coaching": coaching_payload,
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
        """Preserve validated reply text and strip legacy first-turn headers.

        PatientReplyService validates fresh model output and treats leaked
        metadata labels as invalid. The strip path below is retained only for
        injected or legacy reply payloads that predate that validation metadata.
        """
        try:
            validation = reply_payload.get("reply_validation")
            if isinstance(validation, dict):
                reply_payload["patient_reply"] = (
                    reply_payload.get("patient_reply", "") or ""
                ).strip()
                return
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
        - coach_classify: configured main model primary, Flash fallback(s)
        - otherwise (e.g., endgame_detect): Flash primary, configured main model fallback
        """
        lp = (log_path or "").lower()
        # Start with configured fallbacks, ensuring uniqueness and preserving order
        configured_primary = self.model_id
        try:
            cfg_fallbacks = [m for m in (self.model_fallbacks or []) if m]
        except Exception as e:
            self.logger.debug(f"Failed to resolve model fallbacks: {e}")
            cfg_fallbacks = []
        flash = DEFAULT_MODEL_FLASH
        if lp == "coach_classify":
            fb = [x for x in ([flash] + cfg_fallbacks) if x]
            return configured_primary, fb
        fb = [x for x in ([configured_primary] + cfg_fallbacks) if x]
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
