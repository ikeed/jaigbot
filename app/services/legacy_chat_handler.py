"""
Legacy chat handler for non-coaching requests.

This service handles the traditional chat flow:
1. Direct LLM generation with existing system prompt
2. Generate response with safety checks  
3. Update conversation history
4. Build basic response structure

Behavior-preserving extraction from the else/fallback path in app.main.chat().
"""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import Request

from app.models import ChatRequest
from app.services.chat_context import ChatContext
from app.services.security_guard import JailbreakGuard
from app.services.vertex_helpers import vertex_call_with_fallback_text
from app.vertex import VertexClient


class LegacyChatHandler:
    """Handles the traditional non-coaching chat flow."""
    
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
        self.vertex_location = vertex_config["vertex_location"]
        self.model_id = vertex_config["model_id"]
        self.model_fallbacks = vertex_config["model_fallbacks"]
        self.temperature = vertex_config["temperature"]
        self.max_tokens = vertex_config["max_tokens"]
        self.client_cls = vertex_config.get("client_cls") or VertexClient
        
        self.memory_enabled = memory_config["enabled"]
        self.memory_max_turns = memory_config["max_turns"]
        
        # Initialize helper services
        self.jailbreak_guard = JailbreakGuard()
    
    async def handle(
        self, req: Request, body: ChatRequest, ctx: ChatContext
    ) -> Dict[str, Any]:
        """Handle the traditional chat flow."""
        started = time.time()
        
        # Check for jailbreak attempts early
        is_jb, jb_matches = self.jailbreak_guard.detect(body.message)
        if is_jb:
            return {
                "reply": "I'm not able to help with that request. Let's focus on clinical conversations instead.",
                "model": self.model_id,
                "latency_ms": int((time.time() - started) * 1000),
                "jailbreak_detected": True,
            }
        
        # Build complete prompt from history + current message
        full_prompt = self._build_full_prompt(ctx, body.message)
        
        # Generate response with fallbacks
        reply_text = await self._generate_reply(full_prompt)

        # If first assistant turn this session, strip accidental scenario headers
        try:
            if not (ctx.parent_last or "").strip():
                from app.services.chat_helpers import strip_appointment_headers
                reply_text = strip_appointment_headers(reply_text)
        except Exception:
            pass
        
        # Update conversation history
        await self._update_conversation_history(ctx.session_id, body.message, reply_text)
        
        # Calculate final latency
        latency_ms = int((time.time() - started) * 1000)
        
        # Log successful completion
        from app.telemetry.events import log_event as telemetry_log_event
        telemetry_log_event(
            self.logger,
            "legacy_turn", 
            status="ok",
            latencyMs=latency_ms,
            modelId=self.model_id,
            sessionId=ctx.session_id,
        )
        
        # Determine which model actually produced the response (fallback-aware)
        try:
            from app.services.vertex_helpers import get_last_model_used
            model_used = get_last_model_used() or self.model_id
        except Exception:
            model_used = self.model_id

        return {
            "reply": reply_text,
            "model": model_used,
            "latency_ms": latency_ms,
        }
    
    def _build_full_prompt(self, ctx: ChatContext, current_message: str) -> str:
        """Build complete prompt from system + history + current message."""
        # Start with system instruction if available
        parts = []
        
        if ctx.system_instruction:
            parts.append(ctx.system_instruction)
        
        # Add conversation history
        if ctx.history_text:
            parts.append(ctx.history_text)
        
        # Add current user message
        parts.append(f"User: {current_message}")
        parts.append("Assistant:")
        
        return "\n\n".join(parts)
    
    async def _generate_reply(self, prompt: str) -> str:
        """Generate reply using Vertex AI with fallbacks."""
        from app.vertex import VertexAIError
        
        try:
            raw_response = vertex_call_with_fallback_text(
                project=self.project_id,
                region=self.vertex_location,
                primary_model=self.model_id,
                fallbacks=self.model_fallbacks,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                prompt=prompt,
                system_instruction=None,  # System prompt already in main prompt
                log_path="legacy_chat",
                logger=self.logger,
                client_cls=self.client_cls,
            )
            
            return (raw_response or "").strip() or "I'm sorry, I didn't understand that. Could you please rephrase?"
            
        except VertexAIError as e:
            # Re-raise VertexAI errors so the orchestrator can handle them properly
            raise
        except Exception as e:
            self.logger.error("Legacy chat generation failed: %s", e)
            return "I apologize, but I'm having trouble processing your request right now. Please try again."
    
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