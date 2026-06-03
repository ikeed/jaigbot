import logging
import uuid
from typing import Any, Dict, List, Optional

import chainlit as cl
from chainlit.context import context as cl_context

from app.chainlit_thread_state import get_current_thread_id, set_current_thread_id
from app.chat_roles import (
    ROLE_ASSISTANT,
    ROLE_COACH,
    ROLE_SYSTEM,
    ROLE_USER,
    is_scenario_card
)
from app.config import settings
from app.constants import (
    MSG_INTRO_REQUIRED,
    MSG_DUPLICATE_TAB,
    MSG_RESUME_THREAD,
)
from app.persona import DEFAULT_CHARACTER, DEFAULT_SCENE
from app.services.chainlit.backend_client import BackendClient
from app.services.chainlit.session_manager import SessionManager
from app.services.chainlit.ui_handler import UIHandler

logger = logging.getLogger(__name__)

class ChainlitOrchestrator:
    """Orchestrates the high-level flow of the Chainlit application."""

    def __init__(
        self,
        backend_client: BackendClient,
        ui_handler: UIHandler,
        session_manager: SessionManager
    ):
        self.backend = backend_client
        self.ui = ui_handler
        self.session = session_manager

    async def handle_chat_start(self):
        """Main entry point for starting or resuming a chat session."""
        try:
            user_id = self.session.get_user_identifier()
            if not self._has_seen_intro_locally_or_persistently(user_id):
                self.session.intro_pending = True
                await self.ui.send_window_message({"type": MSG_INTRO_REQUIRED})
                return

            reconnect_thread_id = self._get_reconnect_thread_id(user_id)
            if reconnect_thread_id:
                logger.info("Redirecting reconnect to persisted thread: %s", reconnect_thread_id)
                await self.ui.send_window_message({
                    "type": MSG_RESUME_THREAD,
                    "threadId": reconnect_thread_id,
                })
                return

            self.session.intro_pending = False
            await self._start_scenario_flow()
        except Exception as e:
            await self._report_error_silently(e, "handle_chat_start")
            await self.ui.show_error("An error occurred while starting the chat. Please try refreshing.")

    async def handle_user_message(self, message: cl.Message):
        """Processes an incoming user message."""
        if self.session.session_ended:
            await self.ui.show_error("This session has ended. Please start a new chat.")
            return
        if self.session.intro_pending:
            await self.ui.send_window_message({"type": MSG_INTRO_REQUIRED})
            return

        content = message.content.strip()
        if not content:
            await self.ui.show_error("Please enter a message.")
            return

        # Update UI for user message
        await self.ui.send_user_message_update(message)

        # Update local history
        history = self.session.history
        history.append({"role": ROLE_USER, "content": content})
        self.session.history = history

        try:
            # Call backend
            coach_enabled = bool(settings.CHAINLIT_COACH_DEFAULT if settings.CHAINLIT_COACH_DEFAULT is not None else settings.AIMS_COACHING_ENABLED)
            data = await self.backend.send_chat_message(
                message=content,
                session_id=self.session.session_id,
                character=self.session.character,
                scene=self.session.scene,
                user_info=self._get_user_info(),
                coach_enabled=coach_enabled
            )

            # Handle response components
            await self._process_backend_response(data)

        except Exception as e:
            await self._report_error_silently(e, "handle_user_message")
            await self.ui.show_error(f"Error: {str(e)}")

    async def handle_session_resume(self, thread: Dict[str, Any]):
        """Rehydrates session state from a resumed Chainlit thread."""
        try:
            user_id = self.session.get_user_identifier()
            if not self._has_seen_intro_locally_or_persistently(user_id):
                self.session.intro_pending = True
                await self.ui.send_window_message({"type": MSG_INTRO_REQUIRED})
                return

            metadata = (thread or {}).get("metadata") or {}
            thread_id = (thread or {}).get("id") or self._get_thread_id()
            
            # Resolve Session ID
            session_id = self._resolve_session_id(thread_id, metadata.get("session_id"))
            self.session.session_id = session_id
            
            if user_id and thread_id:
                set_current_thread_id(user_id, thread_id)

            connection_id = self._ensure_connection_id()
            
            # Sync with backend
            try:
                metadata_history = metadata.get("history") if isinstance(metadata.get("history"), list) else []
                init_data = await self.backend.initialize_session(
                    session_id=session_id,
                    connection_id=connection_id,
                    persona_id=None,
                    user_info=self._get_user_info(),
                    character=metadata.get("character"),
                    scene=metadata.get("scene"),
                    initial_card=self._recover_scenario_card(metadata_history)
                )

                if init_data.get("alreadyActive"):
                    await self.ui.send_window_message({"type": MSG_DUPLICATE_TAB})
                    return

                if init_data.get("character"):
                    self.session.character = init_data.get("character")
                if init_data.get("scene"):
                    self.session.scene = init_data.get("scene")

                # Always refresh history from backend source of truth
                history = await self.backend.fetch_history(session_id)
                self.session.history = history
            except Exception as e:
                logger.debug(f"Failed to refresh history during resume (non-fatal): {e}")
                pass

            # Fallbacks for missing state
            if self.session.character is None:
                self.session.character = settings.CHARACTER_SYSTEM or DEFAULT_CHARACTER
            if self.session.scene is None:
                self.session.scene = settings.SCENE_OBJECTIVES or DEFAULT_SCENE

        except Exception as e:
            await self._report_error_silently(e, "handle_session_resume")
            await self.ui.show_error("An error occurred while resuming the chat.")

    async def handle_report_issue(self, reason: str):
        """Handles user-initiated issue reporting."""
        try:
            await self.backend.report_issue(
                session_id=self.session.session_id,
                reason=reason,
                user_info=self._get_user_info()
            )
            self.session.session_ended = True
            self.session.history = []
            await self.ui.show_error(
                "Thank you for your report. The scenario has been ended and logged for review. "
                "Please start a new chat to continue."
            )
        except Exception as e:
            await self.ui.show_error(f"An error occurred while reporting: {str(e)}")

    # --- Private Helpers ---
    async def _start_scenario_flow(self):
        logger.info("Starting scenario flow")
        connection_id = self._ensure_connection_id()
        session_id = self._resolve_session_id(self._get_thread_id())
        self.session.session_id = session_id
        
        await self._bind_thread(session_id)

        # Fetch history & recover persona
        history = await self.backend.fetch_history(session_id)
        persona_id = self._recover_persona_from_history(history)

        # Init session
        logger.info("Initializing session with backend: %s", session_id)
        session_data = await self.backend.initialize_session(
            session_id=session_id,
            connection_id=connection_id,
            persona_id=persona_id,
            user_info=self._get_user_info(),
            force=self.session.query_params.get("force") == "true"
        )

        if session_data.get("alreadyActive"):
            await self.ui.send_window_message({"type": MSG_DUPLICATE_TAB})
            return

        logger.info("Session data received from backend.")
        logger.debug("Character: %s, Scene: %s", session_data.get("character"), session_data.get("scene"))
        # Update local state
        self.session.character = session_data.get("character")
        self.session.scene = session_data.get("scene")
        user_card = session_data.get("initialCard")

        if not self.session.history:
            self.session.history = history if history else []

        if history:
            logger.info("Injecting scenario into scene from history")
            self._inject_scenario_into_scene(history, user_card)
        else:
            logger.info("Presenting scenario card to UI")
            await self.ui.present_scenario_card(user_card)
            new_history = [{"role": ROLE_SYSTEM, "content": user_card}]
            self.session.history = new_history
            self._inject_scenario_into_scene(new_history, user_card)

        logger.info("Running preflight checks")
        await self._run_preflight_checks()
        logger.info("Startup flow complete")

    def _has_seen_intro_locally_or_persistently(self, user_id: Optional[str]) -> bool:
        if self.session.local_intro_seen:
            return True
        if not user_id:
            return False
            
        try:
            from app.main import MEMORY_STORE
            # Legacy and current keys
            prefix = f"aims:{settings.APP_ENV}:intro_seen:"
            legacy_prefix = "aims:intro_seen:"
            key = f"{prefix}{user_id.strip().lower()}"
            legacy_key = f"{legacy_prefix}{user_id.strip().lower()}"
            
            value = MEMORY_STORE.get(key) or MEMORY_STORE.get(legacy_key)
            return bool(value.get("seen")) if isinstance(value, dict) else bool(value)
        except Exception as e:
            logger.debug(f"Error checking intro status in MEMORY_STORE: {e}")
            return False

    def _ensure_connection_id(self) -> str:
        cid = self.session.connection_id
        if not cid:
            cid = str(uuid.uuid4())
            self.session.connection_id = cid
        return cid

    def _get_reconnect_thread_id(self, user_id: Optional[str]) -> Optional[str]:
        if self.session.query_params.get("aims_new") == "1":
            return None
        persisted_thread_id = get_current_thread_id(user_id)
        context_thread_id = self._get_thread_id()
        if persisted_thread_id and persisted_thread_id != context_thread_id:
            return persisted_thread_id
        return None

    def _resolve_session_id(self, thread_id: Optional[str], metadata_id: Optional[str] = None) -> str:
        current = self.session.session_id
        fixed = settings.FIXED_SESSION_ID or settings.SESSION_ID
        
        if fixed: return fixed
        if metadata_id: return metadata_id
        if thread_id: return thread_id
        return current or str(uuid.uuid4())

    def _get_user_info(self) -> Optional[Dict[str, Any]]:
        user = self.session.user
        if not user: return None
        return {"identifier": user.identifier, "metadata": user.metadata}

    def _get_thread_id(self) -> Optional[str]:
        return getattr(getattr(cl_context, "session", None), "thread_id", None)

    async def _bind_thread(self, session_id: str):
        thread_id = self._get_thread_id()
        user = self.session.user
        if not thread_id or not user: return
        
        try:
            from chainlit.data import get_data_layer
            dl = get_data_layer()
            if not dl: return
            
            persisted = await dl.get_user(user.identifier) or await dl.create_user(user)
            if persisted:
                await dl.update_thread(thread_id=thread_id, user_id=persisted.id, metadata={"session_id": session_id})
                set_current_thread_id(user.identifier, thread_id)
        except Exception as e:
            logger.debug(f"Failed to bind thread (non-fatal): {e}")
            pass

    def _recover_persona_from_history(self, history: List[Dict[str, Any]]) -> Optional[str]:
        for msg in history:
            content = msg.get("content", "")
            if (msg.get("role") or ROLE_ASSISTANT).lower().strip() in {ROLE_SYSTEM, ROLE_ASSISTANT} and is_scenario_card(content):
                for line in content.splitlines():
                    for prefix in ["Persona: ", "Person: ", "Parent: ", "Parent/Patient: "]:
                        if line.startswith(prefix):
                            return line.replace(prefix, "").strip()
        return None

    def _recover_scenario_card(self, history: List[Dict[str, Any]]) -> Optional[str]:
        for msg in history:
            content = msg.get("content", "")
            if (msg.get("role") or ROLE_ASSISTANT).lower().strip() in {ROLE_SYSTEM, ROLE_ASSISTANT} and is_scenario_card(content):
                return content
        return None

    def _inject_scenario_into_scene(self, history: List[Dict[str, Any]], default_card: str):
        scene = self.session.scene or ""
        if "Scenario details" in scene: return
        
        card = self._recover_scenario_card(history) or default_card
        suffix = f"\n\nScenario details (use these exact names; do not change them):\n{card}\n\nIf asked for names, respond naturally but keep the same names."
        self.session.scene = scene + suffix

    async def _process_backend_response(self, data: Dict[str, Any]):
        history = self.session.history
        
        # 1. Coaching
        coaching = data.get("coaching")
        if coaching:
            parts = []
            if coaching.get("step"): parts.append(f"Detected step: {coaching['step']}")
            if coaching.get("reasons"): parts.append(f"Feedback: {coaching['reasons'][0]}")
            if coaching.get("tips"): parts.append(f"Tip: {coaching['tips'][0]}")
            
            if parts:
                coach_text = " | ".join(parts)
                history.append({"role": ROLE_COACH, "content": coach_text})
                await self.ui.send_coach_message(coach_text)

        # 2. Assistant Reply
        reply = data.get("reply")
        if reply:
            history.append({"role": ROLE_ASSISTANT, "content": reply})
            await self.ui.send_assistant_reply(reply)

        # 3. Coach Post (Game Over)
        coach_post = data.get("coachPost")
        if coach_post:
            title = coach_post.get("title") or "✅ Scenario complete"
            combined = "\n".join([title, *(coach_post.get("lines") or [])])
            await self.ui.send_coach_message(combined)

        self.session.history = history

    async def _run_preflight_checks(self):
        if not await self.backend.check_health():
            await self.ui.show_error("Backend is not reachable. Ensure it is running.")
            return

        try:
            config = await self.backend.get_config()
            proj = config.get("projectId") or config.get("project_id") or config.get("project")
            if proj in (None, "", "<unset>"):
                await self.ui.show_error("Warning: Backend PROJECT_ID appears unset.")
        except Exception as e:
            logger.debug(f"Failed to check backend config during preflight: {e}")
            pass

        try:
            mc = await self.backend.check_model()
            if mc.get("available") is False:
                await self.ui.show_error(f"Model '{mc.get('modelId')}' not available in '{mc.get('region')}'.")
        except Exception as e:
            logger.debug(f"Failed to check model availability during preflight: {e}")
            pass

    async def _report_error_silently(self, error: Exception, context: str):
        try:
            await self.backend.report_issue(
                session_id=self.session.session_id or f"error-{uuid.uuid4()}",
                reason=f"Auto-reported error in {context}: {str(error)}",
                user_info=self._get_user_info()
            )
        except Exception as e:
            logger.error(f"Failed to report error silently: {e}")
            pass
