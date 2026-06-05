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

from fastapi import HTTPException, Request, BackgroundTasks
from fastapi.responses import JSONResponse

from app.models import ChatRequest, ReportRequest
from app.services.chat_context import ChatContextBuilder, ChatContext
from app.services.session_service import SessionService, CookieSettings
from app.services.storage_service import storage_service
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
        self.background_tasks: Optional[BackgroundTasks] = None
        self.memory_store = memory_store
        self.logger = logger
        
        # Extract config values for easier access with safe defaults
        self.memory_enabled = memory_config.get("enabled", True)
        self.memory_max_turns = memory_config.get("max_turns", 10)
        self.memory_ttl_seconds = memory_config.get("ttl_seconds", 3600)
        
        self.aims_coaching_enabled = aims_config.get("enabled", False)
        self.force_coach_default = bool(aims_config.get("force_default", False))
        
        self.project_id = vertex_config.get("project_id")
        self.region = vertex_config.get("region", "us-central1")
        self.vertex_location = vertex_config.get("vertex_location", "us-central1")
        self.model_id = vertex_config.get("model_id")
        self.model_fallbacks = vertex_config.get("model_fallbacks", [])
        self.temperature = vertex_config.get("temperature", 0.0)
        self.max_tokens = vertex_config.get("max_tokens", 1024)
        self.client_cls = vertex_config.get("client_cls")
        self.expose_upstream_error = debug_config.get("expose_upstream_error", False)
        self.log_response_preview_max = debug_config.get("log_response_preview_max", 100)
        
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
    
    async def handle_chat(self, req: Request, body: ChatRequest, background_tasks: Optional[BackgroundTasks] = None) -> JSONResponse:
        """Main entry point for chat requests."""
        # Optional: update background_tasks if passed
        self.background_tasks = background_tasks
        
        try:
            # Early validation
            self._validate_request(body)
            
            # Build chat context (session, memory, persona)
            ctx = self.context_builder.build(
                req, body.sessionId, body.character, body.scene, body.userInfo
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
        except Exception as e:
            self.logger.warning(f"UTF-8 encoding failed for message: {e}")
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
                "client_cls": self.client_cls,
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
            except Exception as e:
                self.logger.debug(f"Failed to set sessionId in response (non-fatal): {e}")
                pass
            
            # Add optional coach post for end-game scenarios
            if result.get("coach_post"):
                response_payload["coachPost"] = result["coach_post"]
                response_payload["gameOver"] = True
                
                # Trigger background archive to GCS
                if self.background_tasks:
                    try:
                        mem = self.session_service.get_mem(ctx.session_id)
                        # Use identifier (email) from user_info if present
                        user_id = ctx.user_info.get("identifier") if ctx.user_info else None
                        if not user_id:
                            user_id = "anonymous"
                            
                        # Enrich mem with endgame status for the archive
                        mem["session_ended"] = time.time()
                        self.memory_store[ctx.session_id] = mem
                        archive_data = {
                            **mem,
                            "session_id": ctx.session_id,
                            "user_id": user_id,
                            "game_over": True,
                            "coach_post": result["coach_post"],
                            "exported_via": "endgame"
                        }
                        self.background_tasks.add_task(
                            storage_service.upload_session,
                            ctx.session_id,
                            user_id,
                            archive_data
                        )
                    except Exception as archive_err:
                        self.logger.warning(f"Failed to queue GCS archive for session {ctx.session_id}: {archive_err}")
            
            resp = JSONResponse(status_code=200, content=response_payload)
            
            # Set session cookie
            try:
                self.session_service.apply_cookie(resp, ctx.session_id)
            except Exception as e:
                self.logger.debug(f"Failed to apply session cookie (non-fatal): {e}")
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
                "client_cls": self.client_cls,
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
            except Exception as e:
                self.logger.debug(f"Failed to set sessionId in legacy response (non-fatal): {e}")
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
            except Exception as e:
                self.logger.debug(f"Failed to apply session cookie in legacy path (non-fatal): {e}")
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
        except Exception as e:
            self.logger.debug(f"Failed to apply session cookie (vertex error path): {e}")
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
    
    async def handle_report(self, req: Request, body: ReportRequest, background_tasks: Optional[BackgroundTasks] = None) -> JSONResponse:
        """Handle issue reports by archiving session and clearing it."""
        self.background_tasks = background_tasks
        session_id = body.sessionId
        self.logger.info(f"Report received for session: {session_id}, reason: {body.reason}")
        
        try:
            # Fetch existing memory
            mem = self.session_service.get_mem(session_id)
            
            # Identify user_id
            user_info = body.userInfo or (mem.get("user_info") if mem else None)
            user_id = "anonymous"
            if isinstance(user_info, dict):
                user_id = str(user_info.get("identifier") or "anonymous")

            if not mem:
                # If no session found in memory, try to fetch from GCS
                self.logger.info(f"Session {session_id} not in memory, checking GCS for user {user_id}")
                downloaded = storage_service.download_session(session_id, user_id)
                mem = downloaded or {}
                
                if not mem:
                    # No conversation history, but still archive the report itself
                    self.logger.info(f"No prior session data for {session_id}, creating report-only archive")
                    mem = {"history": [], "character": None, "scene": None}

            self.logger.info(f"Archiving session {session_id} for user {user_id}")
            # Record session_ended timestamp
            mem["session_ended"] = time.time()
            # Prepare archive data with the extra error_report key
            archive_data = {
                **mem,
                "session_id": session_id,
                "user_id": user_id,
                "game_over": True,
                "error_report": body.reason,
                "reported_at": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }

            # Trigger background archive
            if self.background_tasks:
                self.background_tasks.add_task(
                    storage_service.upload_session,
                    session_id,
                    user_id,
                    archive_data,
                    is_report=True
                )
            else:
                # Fallback to synchronous if no background tasks (rare)
                storage_service.upload_session(session_id, user_id, archive_data, is_report=True)

            # Clear session from memory store
            self.memory_store.pop(session_id, None)

            return JSONResponse(content={"status": "ok", "message": "Issue reported and session ended."})

        except Exception as e:
            self.logger.error(f"Error handling report for session {session_id}: {e}", exc_info=True)
            return self._build_error_response(req, e, 500, "Internal server error during report")

    def _get_request_id(self, request: Request) -> Optional[str]:
        """Extract request ID from headers or generate one."""
        h = request.headers.get("x-cloud-trace-context") or request.headers.get("x-request-id")
        if h:
            return h
        
        try:
            return getattr(request.state, "request_id", None) or self._generate_uuid()
        except Exception as e:
            self.logger.debug(f"Error retrieving request ID: {e}")
            return self._generate_uuid()
    
    @staticmethod
    def _generate_uuid() -> str:
        """Generate a UUID string."""
        import uuid
        return str(uuid.uuid4())
