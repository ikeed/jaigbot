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

import json
import time
import asyncio
import uuid
import os
from typing import Any, Dict

from fastapi import Request

from app.models import ChatRequest
from app.services.chat_context import ChatContext
from app.services.coach_post import VaccineRelevanceGate, AimsPostProcessor, EndGameDetector
from app.services.coach_safety import detect_advice_patterns
from app.services.conversation_service import (
    maybe_add_parent_concern as svc_maybe_add_parent_concern,
    mark_mirrored_multi as svc_mark_mirrored_multi, 
    mark_secured_by_topic as svc_mark_secured_by_topic,
    concern_topic as svc_concern_topic,
)
from app.services.prompt_builders import AimsPromptBuilder
from app.services.security_guard import JailbreakGuard
from app.services.vertex_helpers import vertex_call_with_fallback_text, vertex_call_with_fallback_json
from app.prompts.aims import build_patient_reply_prompt
from app.telemetry.events import log_event as telemetry_log_event, truncate_for_log as telemetry_truncate
from app.vertex import VertexClient
from app.json_schemas import REPLY_SCHEMA, CLASSIFY_SCHEMA, ENDGAME_DETECT_SCHEMA, validate_json


class AimsCoachingHandler:
    """Handles the full AIMS coaching flow."""
    
    # Topical cues for concern tracking (behavior-preserving constants)
    _TOPICAL_CUES = {
        "autism": ["autism", "asd"],
        "immune_load": ["too many", "too soon", "immune", "immune system", "overload", 
                       "immune overload", "immune system load", "viral load"],
        "side_effects": ["side effect", "adverse event", "vaers", "reaction", 
                        "fever", "swelling", "redness"],
        "ingredients": ["thimerosal", "aluminum", "adjuvant", "preservative", "ingredient"],
        "schedule_timing": ["schedule", "spacing", "delay", "alternative schedule", "wait"],
        "effectiveness": ["effective", "efficacy", "works", "breakthrough"],
        "trust": ["data", "study", "studies", "pharma", "big pharma", "trust"],
    }
    
    def __init__(
        self,
        *,
        memory_store: Any,
        vertex_config: dict[str, Any],
        memory_config: dict[str, Any],
        logger: Any,
    ):
        self.memory_store = memory_store
        self.vertex_config = vertex_config
        self.memory_config = memory_config
        self.logger = logger
        
        # Extract frequently used config
        self.project_id = vertex_config["project_id"]
        self.region = vertex_config["region"] 
        self.vertex_location = vertex_config["vertex_location"]
        self.model_id = vertex_config["model_id"]
        self.model_fallbacks = vertex_config["model_fallbacks"]
        self.temperature = vertex_config["temperature"]
        self.max_tokens = vertex_config["max_tokens"]
        
        # Per-call tuning (env-configurable) for latency/cost-sensitive JSON tasks
        self.classify_temperature = float(os.getenv("AIMS_CLASSIFY_TEMPERATURE", "0.1"))
        self.classify_max_tokens = int(os.getenv("AIMS_CLASSIFY_MAX_TOKENS", "256"))
        self.endgame_temperature = float(os.getenv("AIMS_ENDGAME_TEMPERATURE", "0.1"))
        self.endgame_max_tokens = int(os.getenv("AIMS_ENDGAME_MAX_TOKENS", "192"))
        self.classify_budget_s = float(os.getenv("AIMS_CLASSIFY_BUDGET_S", "3.0"))

        # Allow tests to monkeypatch the client via app.main.VertexClient
        self.client_cls = vertex_config.get("client_cls", None) or VertexClient
        
        self.memory_enabled = memory_config["enabled"]
        self.memory_max_turns = memory_config["max_turns"]
        
        # Initialize helper services
        self.jailbreak_guard = JailbreakGuard()
    
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
            except Exception:
                return str(uuid.uuid4())

        request_id = _req_id()

        # Load AIMS mapping (cached at app level)
        mapping = await self._load_aims_mapping()
        
        # Step 1: Deterministic classification/scoring
        cls_payload = self._get_deterministic_classification(
            ctx.parent_last, body.message, mapping
        )
        
        # Step 2 & 5 in parallel: Enhanced LLM classification and patient reply generation
        # Emit begin markers and start both tasks concurrently, then await both.
        cls_start = time.time()
        reply_start = time.time()
        telemetry_log_event(
            self.logger,
            "aims_classify_begin",
            sessionId=ctx.session_id,
            requestId=request_id,
            modelId=self.model_id,
        )
        telemetry_log_event(
            self.logger,
            "aims_reply_begin",
            sessionId=ctx.session_id,
            requestId=request_id,
            modelId=self.model_id,
        )

        task_cls = asyncio.create_task(
            self._enhance_with_llm_classification(cls_payload, body.message, ctx, mapping)
        )
        task_reply = asyncio.create_task(
            self._generate_patient_reply(body.message, ctx.history_text, req, ctx.session_id)
        )

        # Await classification with a time budget; on timeout, keep deterministic result
        timed_out = False
        try:
            cls_payload = await asyncio.wait_for(task_cls, timeout=self.classify_budget_s)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                task_cls.cancel()
            except Exception:
                pass
        # Try to snapshot model used for classification (may be approximate if overwritten by parallel call)
        try:
            from app.services.vertex_helpers import get_last_model_used
            model_used_cls = get_last_model_used() or self.model_id
        except Exception:
            model_used_cls = self.model_id
        telemetry_log_event(
            self.logger,
            "aims_classify_end",
            sessionId=ctx.session_id,
            requestId=request_id,
            durationMs=int((time.time() - cls_start) * 1000),
            modelUsed=model_used_cls,
            step=cls_payload.get("step"),
            score=cls_payload.get("score"),
            timedOut=timed_out,
        )

        reply_payload = await task_reply
        try:
            from app.services.vertex_helpers import get_last_model_used
            model_used_reply = get_last_model_used() or self.model_id
        except Exception:
            model_used_reply = self.model_id
        telemetry_log_event(
            self.logger,
            "aims_reply_end",
            sessionId=ctx.session_id,
            requestId=request_id,
            durationMs=int((time.time() - reply_start) * 1000),
            modelUsed=model_used_reply,
            textLen=len((reply_payload.get("patient_reply") or "").strip()),
        )

        # Step 3: Update AIMS state and provide coaching guidance (after classification completes)
        await self._update_aims_state(ctx.session_id, cls_payload, body.message, ctx.parent_last)

        # Step 4: Persist AIMS metrics (after state update)
        await self._persist_aims_metrics(ctx.session_id, cls_payload)
        
        # Step 5: Generate patient reply (emit begin/end markers)
        reply_start = time.time()
        telemetry_log_event(
            self.logger,
            "aims_reply_begin",
            sessionId=ctx.session_id,
            requestId=request_id,
            modelId=self.model_id,
        )
        reply_payload = await self._generate_patient_reply(
            body.message, ctx.history_text, req, ctx.session_id
        )
        try:
            from app.services.vertex_helpers import get_last_model_used
            model_used_reply = get_last_model_used() or self.model_id
        except Exception:
            model_used_reply = self.model_id
        telemetry_log_event(
            self.logger,
            "aims_reply_end",
            sessionId=ctx.session_id,
            requestId=request_id,
            durationMs=int((time.time() - reply_start) * 1000),
            modelUsed=model_used_reply,
            textLen=len((reply_payload.get("patient_reply") or "").strip()),
        )

        # If this is the first assistant turn in the session, strip any accidental
        # scenario headers from the parent reply to avoid duplicating the UI card.
        try:
            if not (ctx.parent_last or "").strip():
                from app.services.chat_helpers import strip_appointment_headers
                pr = reply_payload.get("patient_reply", "")
                reply_payload["patient_reply"] = strip_appointment_headers(pr)
        except Exception:
            pass
        
        # Step 6: Update conversation history
        await self._update_conversation_history(
            ctx.session_id, body.message, reply_payload.get("patient_reply", "")
        )
        
        # Step 7: Build session metrics
        session_obj = await self._build_session_metrics(ctx.session_id)
        
        # Step 8: Check for end-game scenarios
        coach_post = await self._check_end_game(ctx.session_id, reply_payload, session_obj)
        
        # Calculate final latency
        latency_ms = int((time.time() - started) * 1000)
        
        # Log successful completion
        telemetry_log_event(
            self.logger,
            "aims_turn",
            status="ok",
            latencyMs=latency_ms,
            modelId=self.model_id,
            sessionId=ctx.session_id,
            step=cls_payload.get("step"),
            score=cls_payload.get("score"),
        )
        
        # Return structured result
        # Report the actual model used (considering fallbacks) when available
        try:
            from app.services.vertex_helpers import get_last_model_used
            model_used = get_last_model_used() or self.model_id
        except Exception:
            model_used = self.model_id

        result = {
            "reply": reply_payload.get("patient_reply", ""),
            "model": model_used,
            "latency_ms": latency_ms,
            "coaching": {
                "step": cls_payload.get("step"),
                "score": cls_payload.get("score"),
                "reasons": cls_payload.get("reasons", []),
                "tips": cls_payload.get("tips", []),
            },
            "session": session_obj,
        }
        
        if coach_post:
            result["coach_post"] = coach_post
        
        return result
    
    async def _load_aims_mapping(self) -> Dict[str, Any]:
        """Load and cache AIMS mapping."""
        # Import here to avoid circular imports
        from app.main import app
        
        mapping = getattr(app.state, "aims_mapping", None)
        if mapping is None:
            try:
                from app.aims_engine import load_mapping
                mapping = load_mapping()
            except Exception as e:
                self.logger.warning("AIMS mapping failed to load: %s", e)
                mapping = {}
            app.state.aims_mapping = mapping
        
        return mapping
    
    def _get_deterministic_classification(
        self, parent_last: str, clinician_message: str, mapping: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get deterministic AIMS classification as fallback."""
        from app.aims_engine import evaluate_turn
        
        fb = evaluate_turn(parent_last, clinician_message, mapping)
        return {
            "step": fb.get("step"),
            "score": fb.get("score", 2),
            "reasons": fb.get("reasons", ["deterministic"]),
            "tips": fb.get("tips", []),
        }
    
    async def _enhance_with_llm_classification(
        self, cls_payload: Dict[str, Any], clinician_message: str, 
        ctx: ChatContext, mapping: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Enhance classification with LLM if enabled."""
        from app.main import AIMS_CLASSIFIER_MODE, AIMS_CLASSIFY_CONTEXT_TURNS, AIMS_CLASSIFY_MAX_CONCERNS
        
        # Get prior state for context
        prior_state = await self._get_prior_state(ctx.session_id) if self.memory_enabled else None
        prior_announced = bool((prior_state or {}).get("announced", False))
        prior_phase = (prior_state or {}).get("phase", "PreAnnounce")
        
        # Check if we should use LLM classification
        pre_gate_rapport = (cls_payload.get("step") is None)
        do_llm = (AIMS_CLASSIFIER_MODE in ("hybrid", "llm")) and (not pre_gate_rapport)
        
        if not do_llm:
            return cls_payload
        
        # Build classification prompt
        markers = ((mapping or {}).get("meta", {}) or {}).get("per_step_classification_markers", {})
        markers_text = AimsPromptBuilder.markers_text(markers)
        
        history = ctx.mem.get("history", []) if ctx.mem else []
        recent_ctx = AimsPromptBuilder.recent_context(history, AIMS_CLASSIFY_CONTEXT_TURNS * 2)
        parent_recent_concerns = AimsPromptBuilder.extract_recent_concerns(history, AIMS_CLASSIFY_MAX_CONCERNS)
        
        classify_prompt = AimsPromptBuilder.build_classify_prompt(
            mapping_markers_text=markers_text,
            recent_ctx=recent_ctx,
            parent_recent_concerns=parent_recent_concerns,
            parent_last=ctx.parent_last,
            clinician_last=clinician_message,
            prior_announced=prior_announced,
            prior_phase=prior_phase,
            context_turns=AIMS_CLASSIFY_CONTEXT_TURNS,
        )
        
        # Attempt LLM classification with retry
        used_llm_cls = False
        for attempt in (1, 2):
            try:
                raw = await self._call_vertex_json(
                    classify_prompt,
                    CLASSIFY_SCHEMA,
                    "coach_classify",
                    temperature=self.classify_temperature,
                    max_tokens=self.classify_max_tokens,
                )
                cand = json.loads((raw or "").strip())
                validate_json(cand, CLASSIFY_SCHEMA)
                
                # Clip tips to at most one as policy
                tips = (cand.get("tips") or [])
                if isinstance(tips, list) and len(tips) > 1:
                    tips = tips[:1]
                
                cls_payload = {
                    "step": cand.get("step"),
                    "score": int(cand.get("score", 2)),
                    "reasons": cand.get("reasons") or ["llm"],
                    "tips": tips,
                }
                used_llm_cls = True
                break
                
            except Exception as ve:
                telemetry_log_event(
                    self.logger,
                    "aims_classifier_invalid_json" if attempt == 1 else "aims_classifier_fallback",
                    attempt=attempt,
                    sessionId=ctx.session_id,
                    error=str(ve),
                )
                if attempt == 1:
                    continue
                # On second failure, keep deterministic cls_payload
                break
        
        # Apply a conservative question-guard to reduce obvious mislabels
        if used_llm_cls:
            try:
                if (clinician_message or "").strip().endswith("?") and (cls_payload.get("step") in {"Announce", "Secure"}):
                    cls_payload = dict(cls_payload)
                    cls_payload["step"] = "Inquire"
                    try:
                        cls_payload["score"] = min(2, int(cls_payload.get("score", 2)))
                    except Exception:
                        cls_payload["score"] = 2
            except Exception:
                pass

        # Apply vaccine relevance gating if LLM was used
        if used_llm_cls:
            cls_payload = VaccineRelevanceGate.gate(
                cls_payload=cls_payload,
                clinician_text=clinician_message,
                parent_last=ctx.parent_last,
                parent_recent_concerns=parent_recent_concerns,
                prior_announced=prior_announced,
            )
            
            # Post-hoc corrections and score normalization
            cls_payload = AimsPostProcessor.post_process(cls_payload, clinician_message)
        
        return cls_payload
    
    async def _update_aims_state(
        self, session_id: str, cls_payload: Dict[str, Any], 
        clinician_message: str, parent_last: str
    ) -> None:
        """Update AIMS state and provide coaching guidance."""
        if not (self.memory_enabled and session_id):
            return
        
        try:
            mem = self.memory_store.get(session_id) or {
                "history": [], "character": None, "scene": None, "updated": time.time()
            }
            state = mem.setdefault("aims_state", {
                "announced": False, "phase": "PreAnnounce", 
                "first_inquire_done": False, "pending_concerns": True, 
                "parent_concerns": []
            })
            
            step_current = cls_payload.get("step")
            
            # Add latest parent concern if any, avoiding duplicates by topic
            if parent_last:
                pt_topic = svc_concern_topic(parent_last, self._TOPICAL_CUES)
                existing = state.get("parent_concerns") or []
                if pt_topic is None or not any(c.get("topic") == pt_topic for c in existing):
                    svc_maybe_add_parent_concern(state, parent_last, self._TOPICAL_CUES)
            
            # Apply coaching guidance rules
            self._apply_coaching_guidance(cls_payload, step_current, state, clinician_message, parent_last)
            
            # Update observational state
            self._update_observational_state(state, step_current)
            
            # Persist state
            mem["aims_state"] = state
            mem["updated"] = time.time()
            self.memory_store[session_id] = mem
            
        except Exception:
            self.logger.debug("AIMS state persistence failed for session %s", session_id)
    
    def _apply_coaching_guidance(
        self, cls_payload: Dict[str, Any], step_current: str, state: Dict[str, Any],
        clinician_message: str, parent_last: str
    ) -> None:
        """Apply coaching-specific guidance rules."""
        # Suppress 'what else' caution tip if all known concerns have been mirrored
        if step_current in ("Inquire", "Mirror+Inquire"):
            concerns_list = state.get("parent_concerns") or []
            has_unmirrored = any(not c.get("is_mirrored") for c in concerns_list)
            if not has_unmirrored:
                tip_list = cls_payload.get("tips") or []
                if tip_list:
                    tip0 = (tip_list[0] or "")
                    tip0_l = tip0.lower()
                    if ("what else" in tip0_l) or ("before asking" in tip0_l and 
                                                  ("what else" in tip0_l or "explore and address" in tip0_l)):
                        cls_payload["tips"] = []
        
        # Handle Announce after inquiry
        if step_current == "Announce" and state.get("first_inquire_done", False):
            cls_payload["reasons"] = [
                "Announce after inquiry is allowed, but it can feel abrupt at this point"
            ] + (cls_payload.get("reasons") or [])
            cls_payload.setdefault("tips", []).append(
                "Keep it brief and invite input (e.g., 'How does that sound?')."
            )
            try:
                cls_payload["score"] = min(2, int(cls_payload.get("score", 2)))
            except Exception:
                cls_payload["score"] = 2
        
        # Handle mirroring
        if step_current in ("Mirror", "Mirror+Inquire"):
            svc_mark_mirrored_multi(state, clinician_message, parent_last, self._TOPICAL_CUES)
        
        # Handle securing
        if step_current == "Secure":
            needs_mirror = any(not c.get("is_mirrored") for c in (state.get("parent_concerns") or []))
            if needs_mirror:
                cls_payload["reasons"] = [
                    "Securing before mirroring — allowed, but mirror first so the parent feels heard"
                ] + (cls_payload.get("reasons") or [])
                cls_payload.setdefault("tips", []).append(
                    "Before educating, briefly reflect the concern (e.g., 'It feels like a lot at once — did I get that right?')."
                )
                try:
                    cls_payload["score"] = min(2, int(cls_payload.get("score", 2)))
                except Exception:
                    cls_payload["score"] = 2
            svc_mark_secured_by_topic(state, clinician_message, self._TOPICAL_CUES)
    
    def _update_observational_state(self, state: Dict[str, Any], step_current: str) -> None:
        """Update observational state based on detected step."""
        if step_current == "Announce":
            state["announced"] = True
            if state.get("phase") == "PreAnnounce":
                state["phase"] = "PreAnnounce"  # remain until inquiry begins
        elif step_current in ("Inquire", "Mirror+Inquire"):
            state["first_inquire_done"] = True
            state["phase"] = "InquireMirror"
        elif step_current == "Mirror":
            state["phase"] = "InquireMirror"
        elif step_current == "Secure":
            state["phase"] = "Secure"
            # pending_concerns becomes False if all concerns are secured
            pc = state.get("parent_concerns") or []
            state["pending_concerns"] = not all(
                c.get("is_mirrored") and c.get("is_secured") for c in pc
            ) if pc else False
    
    async def _persist_aims_metrics(self, session_id: str, cls_payload: Dict[str, Any]) -> None:
        """Persist AIMS metrics for session analytics."""
        if not (self.memory_enabled and session_id):
            return
        
        try:
            mem = self.memory_store.get(session_id) or {
                "history": [], "character": None, "scene": None, "updated": time.time()
            }
            aims = mem.setdefault("aims", {
                "perStepCounts": {"Announce": 0, "Inquire": 0, "Mirror": 0, "Secure": 0},
                "scores": {"Announce": [], "Inquire": [], "Mirror": [], "Secure": []},
                "totalTurns": 0
            })
            
            step = cls_payload.get("step")
            # Always count the turn; only score/count recognized AIMS steps
            aims["totalTurns"] = int(aims.get("totalTurns", 0)) + 1
            
            if step in {"Announce", "Inquire", "Mirror", "Secure", "Mirror+Inquire"}:
                score_val = int(cls_payload.get("score", 2))
                if step == "Mirror+Inquire":
                    # Expand into both Mirror and Inquire for metrics
                    aims["perStepCounts"]["Mirror"] = aims["perStepCounts"].get("Mirror", 0) + 1
                    aims["perStepCounts"]["Inquire"] = aims["perStepCounts"].get("Inquire", 0) + 1
                    aims["scores"].setdefault("Mirror", []).append(score_val)
                    aims["scores"].setdefault("Inquire", []).append(score_val)
                else:
                    aims["perStepCounts"][step] = aims["perStepCounts"].get(step, 0) + 1
                    aims["scores"].setdefault(step, []).append(score_val)
                
                # Maintain running averages per step for quick snapshot reads
                ra: dict[str, float] = {}
                for k, arr in (aims.get("scores", {}) or {}).items():
                    if arr:
                        try:
                            ra[k] = sum(arr) / len(arr)
                        except Exception:
                            pass  # ignore non-numeric entries gracefully
                aims["runningAverage"] = ra
            
            mem["aims"] = aims
            mem["updated"] = time.time()
            self.memory_store[session_id] = mem
            
        except Exception:
            self.logger.debug("AIMS metrics persistence failed for session %s", session_id)
    
    async def _generate_patient_reply(
        self, clinician_message: str, history_text: str, req: Request, session_id: str
    ) -> Dict[str, Any]:
        """Generate patient reply with safety checks and jailbreak detection."""
        # Check for jailbreak attempts first
        is_jb, jb_matches = self.jailbreak_guard.detect(clinician_message)
        if is_jb:
            confused = "Um… I'm just a parent here for my child's visit. I'm not sure what you mean — are we still talking about the checkup today?"
            
            telemetry_log_event(
                self.logger,
                "aims_patient_reply_jailbreak_intercept",
                sessionId=session_id,
                patterns=jb_matches,
                requestBody={
                    "message": clinician_message,
                    "coach": True,
                    "sessionId": session_id,
                },
            )
            
            return {"patient_reply": confused}
        
        # Build patient reply prompt
        reply_prompt = build_patient_reply_prompt(
            history_text=history_text,
            clinician_last=clinician_message,
        )
        
        # Attempt to generate reply with retry and safety checks
        for attempt in (1, 2):
            try:
                raw = await self._call_vertex_text(reply_prompt)
                cand = json.loads((raw or "").strip())
                validate_json(cand, REPLY_SCHEMA)
                
                text = cand.get("patient_reply", "").strip()
                
                # Safety post-check: parent should never give advice
                advice_hits = detect_advice_patterns(text)
                if advice_hits:
                    violation_id = str(uuid.uuid4())
                    
                    # Log safety violation
                    req_log = json.dumps({
                        "message": clinician_message,
                        "coach": True,
                        "sessionId": session_id,
                    })
                    
                    telemetry_log_event(
                        self.logger,
                        "aims_patient_reply_safety_violation",
                        sessionId=session_id,
                        violationId=violation_id,
                        patterns=advice_hits,
                        requestBody=telemetry_truncate(req_log, 16384),
                        rawModelResponse=telemetry_truncate(str(raw), 16384),
                        retryUsed=attempt > 1,
                    )
                    
                    return {
                        "patient_reply": f"Error: parent persona generated clinician-style advice (id={violation_id}). Logged for debugging. Please try again."
                    }
                
                # Normal safe path
                return {"patient_reply": text}
                
            except Exception as ve:
                telemetry_log_event(
                    self.logger,
                    "aims_patient_reply_invalid_json",
                    attempt=attempt,
                    sessionId=session_id,
                    jsonInvalid=True,
                    error=str(ve),
                )
                
                if attempt == 1:
                    continue
                
                # Fallback: minimal safe reply template
                fallback_text = "I'm not sure — I have some questions, but I'd like to hear more."
                return {"patient_reply": fallback_text}
        
        # Should not reach here, but provide fallback
        return {"patient_reply": "Okay."}
    
    async def _update_conversation_history(
        self, session_id: str, user_message: str, assistant_reply: str
    ) -> None:
        """Update conversation history in memory."""
        if not (self.memory_enabled and session_id):
            return
        
        try:
            mem = self.memory_store.get(session_id) or {
                "history": [], "character": None, "scene": None, "updated": time.time()
            }
            mem.setdefault("history", []).append({"role": "user", "content": user_message})
            mem["history"].append({"role": "assistant", "content": assistant_reply})
            
            # Trim to last N pairs
            max_items = self.memory_max_turns * 2
            if len(mem["history"]) > max_items:
                mem["history"] = mem["history"][-max_items:]
            
            mem["updated"] = time.time()
            self.memory_store[session_id] = mem
            
        except Exception:
            self.logger.debug("Memory persistence failed for session %s", session_id)
    
    async def _build_session_metrics(self, session_id: str) -> Dict[str, Any] | None:
        """Build session metrics snapshot."""
        if not (self.memory_enabled and session_id):
            return None
        
        try:
            aims = (self.memory_store.get(session_id) or {}).get("aims") or {}
            counts = {"Announce": 0, "Inquire": 0, "Mirror": 0, "Secure": 0}
            counts.update(aims.get("perStepCounts", {}))
            
            # Prefer precomputed runningAverage if available
            running_avg = aims.get("runningAverage") or {}
            if not running_avg:
                for k, arr in (aims.get("scores", {}) or {}).items():
                    if arr:
                        try:
                            running_avg[k] = sum(arr) / len(arr)
                        except Exception:
                            pass
            
            return {
                "totalTurns": aims.get("totalTurns", 0),
                "perStepCounts": counts,
                "runningAverage": running_avg
            }
            
        except Exception:
            return None
    
    async def _check_end_game(
        self, session_id: str, reply_payload: Dict[str, Any], session_obj: Dict[str, Any] | None
    ) -> Dict[str, Any] | None:
        """Check for end-game scenarios and build coach post if needed."""
        # Emit begin marker with gating context
        eg_begin_time = time.time()
        assistant_count = 0
        combined_reply_text = reply_payload.get("patient_reply", "")
        try:
            telemetry_log_event(
                self.logger,
                "aims_endgame_begin",
                sessionId=session_id,
                combinedReplyLen=len((combined_reply_text or "").strip()),
            )
        except Exception:
            pass
        try:
            # Get combined reply text from recent assistant messages
            combined_reply_text = reply_payload.get("patient_reply", "")
            
            if self.memory_enabled and session_id:
                try:
                    mem = self.memory_store.get(session_id) or {}
                    hist = mem.get("history") or []
                    
                    # Collect last two assistant messages
                    acc = []
                    last_user_text = ""
                    for item in reversed(hist):
                        role_i = item.get("role")
                        if role_i == "assistant":
                            txt = (item.get("content") or "").strip()
                            if txt:
                                acc.append(txt)
                        elif role_i == "user" and not last_user_text:
                            last_user_text = (item.get("content") or "").strip()
                        if len(acc) >= 2 and last_user_text:
                            break
                    
                    if acc:
                        # Reverse back to chronological order and join
                        combined_reply_text = " ".join(reversed(acc)).strip()

                    # Count total assistant replies in history for gating
                    try:
                        assistant_count = sum(
                            1
                            for it in hist
                            if it.get("role") == "assistant" and (it.get("content") or "").strip()
                        )
                    except Exception:
                        assistant_count = 0

                    # Heuristic: if clinician explicitly offered follow-up + literature and parent acknowledged, trigger endgame
                    try:
                        lu = (last_user_text or "").strip().lower()
                        pr = (combined_reply_text or "").strip().lower()
                        if lu:
                            followup_offer = any(c in lu for c in (
                                "follow up", "follow-up", "another appointment", "next visit", "come back",
                                "schedule", "set up an appointment", "later appointment", "set up",
                                "book an appointment", "make an appointment", "schedule something", "talk again",
                            ))
                            literature_offer = any(c in lu for c in (
                                "handout", "handouts", "brochure", "pamphlet", "literature", "written info",
                                "information to take home", "take home", "materials", "resource", "printout", "printed info",
                                "reading", "read this", "give you some literature", "leaflet", "info sheet",
                            ))
                            affirmative_ack = any(tok in pr for tok in (
                                "sounds good", "that sounds good", "okay", "ok", "alright", "sure", "yes",
                                "thank you", "thanks", "great", "works for me", "that works",
                                "i appreciate", "let's do that", "let’s do that", "we can do that", "we'll do that",
                            ))
                            if followup_offer and literature_offer and affirmative_ack:
                                # Build coach post now and return
                                lines = [
                                    "Outcome: Parent opted for follow-up and took literature — great coaching!",
                                ]
                                try:
                                    from app.services.coach_post import build_endgame_bullets_fallback
                                    fb_bullets = build_endgame_bullets_fallback(session_obj)
                                    if fb_bullets:
                                        lines.extend(fb_bullets)
                                except Exception:
                                    pass
                                return {"title": "🎉 Great job!", "lines": lines}
                    except Exception:
                        pass

                except Exception:
                    pass
            
            # Heuristic gates to reduce false endgame triggers in very early/short turns
            try:
                # 1) Require at least two assistant replies before we consider the scenario finished
                if locals().get("assistant_count", 0) < 2:
                    return None
                # 2) If the combined reply is very short and lacks vaccine terms, do not trigger
                vax_terms = (
                    "vaccine", "vaccinate", "vaccination", "shot", "shots", "immuniz", "jab", "injection", "mmr", "flu", "booster"
                )
                lt_combined = (combined_reply_text or "").strip().lower()
                if len(lt_combined) < 20 and not any(t in lt_combined for t in vax_terms):
                    return None
            except Exception:
                pass

            # First attempt: LLM-based endgame detection (robust to phrasing differences)
            try:
                detect_prompt = (
                    "You are an expert conversation evaluator for pediatric vaccination visits.\n"
                    "Decide if the PARENT's recent replies indicate the scenario is complete.\n"
                    "Endgame outcomes:\n"
                    "- accepted_now: The parent clearly consented/agreed to vaccinate today (not a question).\n"
                    "- followup_literature: The parent prefers to defer vaccination, plans a follow-up, and accepted written materials.\n"
                    "- not_endgame: Anything else (including questions like 'I have some questions about the vaccination').\n\n"
                    "Consider these latest parent messages (most recent last):\n"
                    f"PARENT_RECENT=\"{combined_reply_text}\"\n\n"
                    "Rules:\n"
                    "- If the statement is conditional or a question (e.g., 'If we go ahead...?', 'Should we proceed?'), do NOT mark accepted_now unless an explicit consent token is present.\n"
                    "- Do not infer acceptance from interest or readiness to discuss.\n"
                    "- Output strict JSON: {\"outcome\": <one of: accepted_now|followup_literature|not_endgame>, \"reasons\":[<short strings>]} only. No markdown.\n"
                )
                raw = await self._call_vertex_json(
                    detect_prompt,
                    ENDGAME_DETECT_SCHEMA,
                    log_path="endgame_detect",
                    temperature=self.endgame_temperature,
                    max_tokens=self.endgame_max_tokens,
                )
                obj = json.loads((raw or "").strip())
                outcome = (obj.get("outcome") or "").strip()
            except Exception:
                outcome = None

            # Fallback: heuristic detector when LLM not confident/available
            if not outcome or outcome == "not_endgame":
                eg = EndGameDetector.detect(combined_reply_text)
                if not eg:
                    # Emit end marker (no outcome)
                    try:
                        telemetry_log_event(
                            self.logger,
                            "aims_endgame_end",
                            sessionId=session_id,
                            durationMs=int((time.time() - eg_begin_time) * 1000),
                            assistantCount=int(assistant_count or 0),
                            outcome="none",
                        )
                    except Exception:
                        pass
                    return None
                outcome = eg.get("reason")

            lines = []
            if outcome == "accepted_now":
                lines.append("Outcome: Parent agreed to vaccinate today — well done!")
            elif outcome == "followup_literature":
                lines.append("Outcome: Parent opted for follow-up and took literature — great coaching!")
            else:
                # Emit end marker (no outcome)
                try:
                    telemetry_log_event(
                        self.logger,
                        "aims_endgame_end",
                        sessionId=session_id,
                        durationMs=int((time.time() - eg_begin_time) * 1000),
                        assistantCount=int(assistant_count or 0),
                        outcome="none",
                    )
                except Exception:
                    pass
                return None

            # Add fallback bullets for end-game summary
            try:
                from app.services.coach_post import build_endgame_bullets_fallback
                fb_bullets = build_endgame_bullets_fallback(session_obj)
                if fb_bullets:
                    lines.extend(fb_bullets)
            except Exception:
                pass
            
            return {"title": "🎉 Great job!", "lines": lines}
            
        except Exception:
            return None
    
    async def _get_prior_state(self, session_id: str) -> Dict[str, Any] | None:
        """Get prior AIMS state for context."""
        try:
            mem = self.memory_store.get(session_id) or {}
            return mem.get("aims_state") or {}
        except Exception:
            return None
    
    async def _call_vertex_text(self, prompt: str) -> str:
        """Call Vertex for text generation with fallbacks (run in thread pool)."""
        return await asyncio.to_thread(
            vertex_call_with_fallback_text,
            project=self.project_id,
            region=self.vertex_location,
            primary_model=self.model_id,
            fallbacks=self.model_fallbacks,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            prompt=prompt,
            system_instruction=None,
            log_path="coach_reply",
            logger=self.logger,
            client_cls=self.client_cls,
        )
    
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
        except Exception:
            cfg_fallbacks = []
        flash = "gemini-2.5-flash"
        if lp == "coach_classify":
            # Pro primary, ensure Flash is in fallbacks
            fb = [x for x in ([flash] + cfg_fallbacks) if x]
            return pro_primary, fb
        # Default: Flash primary, Pro then others as fallbacks
        fb = [x for x in ([pro_primary] + cfg_fallbacks) if x]
        return flash, fb

    async def _call_vertex_json(self, prompt: str, schema: dict, log_path: str, *, temperature: float | None = None, max_tokens: int | None = None) -> str:
        """Call Vertex for JSON generation with fallbacks (non-blocking via thread pool)."""
        primary, fb = self._primary_for_json(log_path)
        # Run blocking SDK call in a worker thread to avoid blocking the event loop
        return await asyncio.to_thread(
            vertex_call_with_fallback_json,
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