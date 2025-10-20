"""
Main chat orchestrator that delegates to coaching or legacy paths.

This service coordinates the high-level flow:
1. Input validation
2. Chat context building 
3. Route to coaching or legacy handler
4. Response formatting
5. Memory persistence
6. Error handling and response building

Behavior-preserving refactoring of the massive app.main.chat() function.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.models import ChatRequest, Coaching, SessionMetrics
from app.services.chat_context import ChatContextBuilder, ChatContext
from app.services.session_service import SessionService, CookieSettings
from app.vertex import VertexAIError


class ChatOrchestrator:
    """Main orchestrator for chat requests - delegates to coaching or legacy paths."""
    
    def __init__(
        self,
        *,
        memory_store: Any,
        session_cookie_settings: dict[str, Any],
        memory_config: dict[str, Any],
        aims_config: dict[str, Any],
        vertex_config: dict[str, Any],
        debug_config: dict[str, Any],
        logger: Any,
    ):
        self.memory_store = memory_store
        self.logger = logger
        
        # Extract config values for easier access
        self.memory_enabled = memory_config["enabled"]
        self.memory_max_turns = memory_config["max_turns"]
        self.memory_ttl_seconds = memory_config["ttl_seconds"]
        
        self.aims_coaching_enabled = aims_config["enabled"]
        self.force_coach_default = bool(aims_config.get("force_default", False))
        
        self.project_id = vertex_config.get("project_id")
        self.region = vertex_config["region"]
        self.vertex_location = vertex_config["vertex_location"]
        self.model_id = vertex_config["model_id"]
        self.model_fallbacks = vertex_config["model_fallbacks"]
        self.temperature = vertex_config["temperature"]
        self.max_tokens = vertex_config["max_tokens"]
        
        self.expose_upstream_error = debug_config["expose_upstream_error"]
        self.log_response_preview_max = debug_config["log_response_preview_max"]
        
        # Initialize session service
        self.session_service = SessionService(
            memory_store,
            cookie=CookieSettings(
                name=session_cookie_settings["name"],
                secure=session_cookie_settings["secure"], 
                samesite=session_cookie_settings["samesite"],
                max_age=session_cookie_settings["max_age"],
            ),
            memory_enabled=self.memory_enabled,
            memory_max_turns=self.memory_max_turns,
            memory_ttl_seconds=self.memory_ttl_seconds,
        )
        
        # Initialize context builder
        self.context_builder = ChatContextBuilder(
            session_service=self.session_service,
            memory_enabled=self.memory_enabled,
            memory_max_turns=self.memory_max_turns,
            memory_ttl_seconds=self.memory_ttl_seconds,
            do_prune_mod=29,
        )
    
    async def handle_chat(self, req: Request, body: ChatRequest) -> JSONResponse:
        """Main entry point for chat requests."""
        try:
            # Early validation
            self._validate_request(body)
            
            # Build chat context (session, memory, persona)
            ctx = self.context_builder.build(
                req, body.sessionId, body.character, body.scene
            )
            
            # Route to appropriate handler
            if self.aims_coaching_enabled and (getattr(body, "coach", False) or self.force_coach_default):
                return await self._handle_coaching_path(req, body, ctx)
            else:
                return await self._handle_legacy_path(req, body, ctx)
                
        except HTTPException:
            # Re-raise HTTP exceptions as-is
            raise
        except Exception as e:
            # Handle unexpected errors
            return self._build_error_response(req, e, 500, "Internal server error")
    
    def _validate_request(self, body: ChatRequest) -> None:
        """Validate the incoming request."""
        # Validate size limit 2 KiB
        try:
            encoded = body.message.encode("utf-8")
        except Exception:
            raise HTTPException(
                status_code=400,
                detail={"error": {"message": "Invalid UTF-8 in message", "code": 400}}
            )
        
        if len(encoded) > 2048:
            raise HTTPException(
                status_code=400,
                detail={"error": {"message": "Message too large (max 2 KiB)", "code": 400}}
            )
    
    async def _handle_coaching_path(
        self, req: Request, body: ChatRequest, ctx: ChatContext
    ) -> JSONResponse:
        """Handle requests with AIMS coaching enabled."""
        from app.services.aims_coaching_handler import AimsCoachingHandler
        
        handler = AimsCoachingHandler(
            memory_store=self.memory_store,
            vertex_config={
                "project_id": self.project_id,
                "region": self.region,
                "vertex_location": self.vertex_location,
                "model_id": self.model_id,
                "model_fallbacks": self.model_fallbacks,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "client_cls": getattr(self, "_client_cls", None),
            },
            memory_config={
                "enabled": self.memory_enabled,
                "max_turns": self.memory_max_turns,
            },
            logger=self.logger,
        )
        
        try:
            result = await handler.handle(req, body, ctx)
            
            # Build response with coaching data
            response_payload = {
                "reply": result["reply"],
                "model": result["model"],
                "latencyMs": result["latency_ms"],
                "coaching": result["coaching"],
                "session": result["session"],
                # Backward-compatible aliases for older clients
                "text": result["reply"],
                "modelId": result["model"],
                "latency_ms": result["latency_ms"],
            }

            # Always include the sessionId for clients that track by id
            try:
                response_payload["sessionId"] = ctx.session_id
            except Exception:
                pass
            
            # Add optional coach post for end-game scenarios
            if result.get("coach_post"):
                response_payload["coachPost"] = result["coach_post"]
                response_payload["gameOver"] = True
            
            resp = JSONResponse(status_code=200, content=response_payload)
            
            # Set session cookie
            try:
                self.session_service.apply_cookie(resp, ctx.session_id)
            except Exception:
                pass
            
            return resp
            
        except VertexAIError as e:
            return self._handle_vertex_error(req, e, ctx.session_id)
    
    async def _handle_legacy_path(
        self, req: Request, body: ChatRequest, ctx: ChatContext
    ) -> JSONResponse:
        """Handle legacy (non-coaching) chat requests."""
        from app.services.legacy_chat_handler import LegacyChatHandler
        
        handler = LegacyChatHandler(
            memory_store=self.memory_store,
            vertex_config={
                "project_id": self.project_id,
                "region": self.region,
                "vertex_location": self.vertex_location,
                "model_id": self.model_id,
                "model_fallbacks": self.model_fallbacks,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "client_cls": getattr(self, "_client_cls", None),
            },
            memory_config={
                "enabled": self.memory_enabled,
                "max_turns": self.memory_max_turns,
            },
            logger=self.logger,
        )
        
        try:
            result = await handler.handle(req, body, ctx)
            
            # Build response
            response_payload = {
                "reply": result["reply"],
                "model": result["model"],
                "latencyMs": result["latency_ms"],
                # Backward-compatible aliases for older clients
                "text": result["reply"],
                "modelId": result["model"],
                "latency_ms": result["latency_ms"],
            }

            # Always include the sessionId for clients that track by id
            try:
                response_payload["sessionId"] = ctx.session_id
            except Exception:
                pass
            
            # Add optional coaching/session if enabled and requested
            if result.get("coaching"):
                response_payload["coaching"] = result["coaching"]
            if result.get("session"):
                response_payload["session"] = result["session"]
            
            resp = JSONResponse(status_code=200, content=response_payload)
            
            # Set session cookie
            try:
                self.session_service.apply_cookie(resp, ctx.session_id)
            except Exception:
                pass
            
            return resp
            
        except VertexAIError as e:
            return self._handle_vertex_error(req, e, ctx.session_id)
    
    def _handle_vertex_error(
        self, req: Request, e: VertexAIError, session_id: str
    ) -> JSONResponse:
        """Handle VertexAI-specific errors with appropriate status codes."""
        req_id = self._get_request_id(req)
        
        if getattr(e, "status_code", None) == 404:
            # Model not found
            guidance = (
                "Publisher model not found or access denied. Verify MODEL_ID spelling and REGION; "
                "ensure Vertex AI API is enabled, billing is active, and your ADC principal has "
                "roles/aiplatform.user. Use GET /models or /modelcheck to confirm availability in "
                "this region. Consider switching MODEL_ID to one listed there (e.g., 'gemini-1.5-pro') "
                "or changing REGION."
            )
            
            payload = {
                "error": {
                    "message": guidance,
                    "code": 404,
                    "requestId": req_id,
                    "region": self.region,
                    "modelId": self.model_id,
                }
            }
            
            if self.expose_upstream_error:
                payload["error"]["upstream"] = str(e)
            
            resp = JSONResponse(status_code=404, content=payload)
        else:
            # Other upstream errors -> 502
            payload = {
                "error": {
                    "message": "Upstream error calling Vertex AI",
                    "code": 502,
                    "requestId": req_id
                }
            }
            
            if self.expose_upstream_error:
                payload["error"]["upstream"] = str(e)
            
            resp = JSONResponse(status_code=502, content=payload)
        
        # Set session cookie
        try:
            self.session_service.apply_cookie(resp, session_id)
        except Exception:
            pass
        
        return resp
    
    def _build_error_response(
        self, req: Request, e: Exception, status_code: int, message: str
    ) -> JSONResponse:
        """Build standardized error response."""
        req_id = self._get_request_id(req)
        
        self.logger.exception("Unexpected error: %s", e)
        self.logger.error(json.dumps({
            "event": "chat",
            "status": "unexpected_error",
            "requestId": req_id,
            "error": str(e),
        }))
        
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "message": message,
                    "code": status_code,
                    "requestId": req_id
                }
            }
        )
    
    def _get_request_id(self, request: Request) -> Optional[str]:
        """Extract request ID from headers or generate one."""
        h = request.headers.get("x-cloud-trace-context") or request.headers.get("x-request-id")
        if h:
            return h
        
        try:
            return getattr(request.state, "request_id", None) or self._generate_uuid()
        except Exception:
            return self._generate_uuid()
    
    def _generate_uuid(self) -> str:
        """Generate a UUID string."""
        import uuid
        return str(uuid.uuid4())