import logging
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.constants import (
    ENDPOINT_HISTORY,
    ENDPOINT_SESSION,
    ENDPOINT_DEREGISTER,
    ENDPOINT_REPORT,
    ENDPOINT_HEALTHZ,
    ENDPOINT_CONFIG,
    ENDPOINT_MODELCHECK,
    PATH_CHAT
)

logger = logging.getLogger(__name__)


class BackendClientError(Exception):
    """Structured backend error surfaced to the Chainlit layer."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        request_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.request_id = request_id
        self.payload = payload or {}


class BackendClient:
    """Encapsulates all communication with the FastAPI backend."""

    def __init__(self, base_url: str = None, timeout: float = None):
        self.base_url = base_url or self._resolve_base_url()
        self.timeout = timeout or settings.CHAINLIT_HTTP_TIMEOUT

    @staticmethod
    def _resolve_base_url() -> str:
        url = settings.BACKEND_URL
        if not url:
            import os
            from app.constants import ENV_BACKEND_URL
            url = os.getenv(ENV_BACKEND_URL) or f"http://localhost:8080{PATH_CHAT}"
        
        return url[:-5] if url.endswith(PATH_CHAT) else url

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.is_success:
            return

        message = f"Backend request failed with status {resp.status_code}."
        request_id: Optional[str] = None
        payload: Dict[str, Any] = {}

        try:
            body = resp.json()
        except Exception:
            body = None

        if isinstance(body, dict):
            payload = body
            error = body.get("error")
            if isinstance(error, dict):
                error_message = error.get("message")
                if isinstance(error_message, str) and error_message.strip():
                    message = error_message.strip()
                error_request_id = error.get("requestId")
                if isinstance(error_request_id, str) and error_request_id.strip():
                    request_id = error_request_id.strip()

        raise BackendClientError(
            message,
            status_code=resp.status_code,
            request_id=request_id,
            payload=payload,
        )

    async def fetch_history(self, session_id: str) -> List[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(
                    f"{self.base_url}{ENDPOINT_HISTORY}", 
                    params={"sessionId": session_id}
                )
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                    return (r.json() or {}).get("history") or []
                else:
                    logger.warning("Failed to fetch history: status=%s, content-type=%s", r.status_code, r.headers.get("content-type"))
        except Exception as e:
            logger.error("Failed to fetch history from backend: %s", e)
            pass
        return []

    async def initialize_session(
        self, 
        session_id: str, 
        connection_id: str, 
        persona_id: Optional[str], 
        user_info: Optional[Dict[str, Any]],
        force: bool = False,
        character: Optional[str] = None,
        scene: Optional[str] = None,
        initial_card: Optional[str] = None
    ) -> Dict[str, Any]:
        payload = {
            "sessionId": session_id,
            "connectionId": connection_id,
            "personaId": persona_id,
            "userInfo": user_info,
            "force": force,
        }
        if character:
            payload["character"] = character
        if scene:
            payload["scene"] = scene
        if initial_card:
            payload["initialCard"] = initial_card

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}{ENDPOINT_SESSION}",
                json=payload,
            )
            self._raise_for_status(resp)
            return resp.json()

    async def send_chat_message(
        self, 
        message: str, 
        session_id: str, 
        character: str, 
        scene: str, 
        user_info: Optional[Dict[str, Any]],
        coach_enabled: bool
    ) -> Dict[str, Any]:
        # Increase timeout for chat calls
        chat_timeout = self.timeout if self.timeout != 15.0 else 120.0
        async with httpx.AsyncClient(timeout=chat_timeout) as client:
            payload = {
                "message": message,
                "sessionId": session_id,
                "character": character,
                "scene": scene,
                "userInfo": user_info,
                "moduleOptions": {"feedbackEnabled": coach_enabled},
            }
            # Use the full URL for chat (including /api/chat if that's what BACKEND_URL points to)
            # Actually, let's just use PATH_CHAT consistently if base_url is root.
            # But get_backend_url in chainlit_app.py was a bit fuzzy.
            # Let's use the resolved base_url + PATH_CHAT.
            resp = await client.post(
                f"{self.base_url}{PATH_CHAT}", 
                json=payload, 
                headers={"Content-Type": "application/json"}
            )
            self._raise_for_status(resp)
            return resp.json()

    async def report_issue(self, session_id: str, reason: str, user_info: Optional[Dict[str, Any]]) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = {
                "sessionId": session_id,
                "reason": reason,
                "userInfo": user_info
            }
            resp = await client.post(f"{self.base_url}{ENDPOINT_REPORT}", json=payload)
            self._raise_for_status(resp)

    async def deregister_session(self, session_id: str, connection_id: str) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{self.base_url}{ENDPOINT_DEREGISTER}",
                json={
                    "sessionId": session_id,
                    "connectionId": connection_id,
                },
            )

    async def check_health(self) -> bool:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for url in [f"{self.base_url}{ENDPOINT_HEALTHZ}", f"{self.base_url}/api{ENDPOINT_HEALTHZ}"]:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        return True
                except Exception as e:
                    logger.debug("Health check failed for %s: %s", url, e)
                    pass
        return False

    async def get_config(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}{ENDPOINT_CONFIG}")
            self._raise_for_status(resp)
            return resp.json()

    async def check_model(self) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}{ENDPOINT_MODELCHECK}")
            self._raise_for_status(resp)
            return resp.json()
