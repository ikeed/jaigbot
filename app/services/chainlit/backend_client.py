import logging
from typing import Any

import httpx

from app.config import settings
from app.constants import (
    ENDPOINT_CONFIG,
    ENDPOINT_DEREGISTER,
    ENDPOINT_HEALTHZ,
    ENDPOINT_HISTORY,
    ENDPOINT_MODELCHECK,
    ENDPOINT_REPORT,
    ENDPOINT_SESSION,
    PATH_CHAT,
)

logger = logging.getLogger(__name__)

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

    async def fetch_history_with_state(self, session_id: str) -> dict[str, Any]:
        """Like fetch_history, but also returns gameOver so callers that need to
        know whether a resumed session already ended don't need a second call."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.get(
                    f"{self.base_url}{ENDPOINT_HISTORY}",
                    params={"sessionId": session_id}
                )
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
                    data = r.json() or {}
                    return {
                        "history": data.get("history") or [],
                        "gameOver": bool(data.get("gameOver")),
                    }
                else:
                    logger.warning("Failed to fetch history: status=%s, content-type=%s", r.status_code, r.headers.get("content-type"))
        except Exception as e:
            logger.error("Failed to fetch history from backend: %s", e)
            pass
        return {"history": [], "gameOver": False}

    async def fetch_history(self, session_id: str) -> list[dict[str, Any]]:
        state = await self.fetch_history_with_state(session_id)
        return state.get("history") or []

    async def initialize_session(
        self,
        session_id: str,
        connection_id: str,
        persona_id: str | None,
        user_info: dict[str, Any] | None,
        force: bool = False,
        character: str | None = None,
        scene: str | None = None,
        initial_card: str | None = None
    ) -> dict[str, Any]:
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
            resp.raise_for_status()
            return resp.json()

    async def send_chat_message(
        self,
        message: str,
        session_id: str,
        character: str,
        scene: str,
        user_info: dict[str, Any] | None,
        coach_enabled: bool
    ) -> dict[str, Any]:
        # Increase timeout for chat calls
        chat_timeout = self.timeout if self.timeout != 15.0 else 120.0
        async with httpx.AsyncClient(timeout=chat_timeout) as client:
            payload = {
                "message": message,
                "sessionId": session_id,
                "character": character,
                "scene": scene,
                "userInfo": user_info,
                "coach": coach_enabled
            }
            resp = await client.post(
                f"{self.base_url}{PATH_CHAT}",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            resp.raise_for_status()
            return resp.json()

    async def report_issue(self, session_id: str, reason: str, user_info: dict[str, Any] | None) -> None:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            payload = {
                "sessionId": session_id,
                "reason": reason,
                "userInfo": user_info
            }
            resp = await client.post(f"{self.base_url}{ENDPOINT_REPORT}", json=payload)
            resp.raise_for_status()

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

    async def get_config(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}{ENDPOINT_CONFIG}")
            resp.raise_for_status()
            return resp.json()

    async def check_model(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(f"{self.base_url}{ENDPOINT_MODELCHECK}")
            resp.raise_for_status()
            return resp.json()
