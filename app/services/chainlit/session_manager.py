from typing import Any

import chainlit as cl
from app.constants import (
    SESSION_CHARACTER,
    SESSION_CONNECTION_ID,
    SESSION_HISTORY,
    SESSION_ID,
    SESSION_INTRO_PENDING,
    SESSION_INTRO_SEEN,
    SESSION_PERSONA_NAME,
    SESSION_QUERY_PARAMS,
    SESSION_SCENE,
    SESSION_SESSION_ENDED,
    SESSION_USER,
)


class SessionManager:
    """Typed wrapper around cl.user_session to avoid magic strings and centralize state management."""

    @property
    def user(self) -> Any:
        return cl.user_session.get(SESSION_USER)

    @property
    def session_id(self) -> str | None:
        return cl.user_session.get(SESSION_ID)

    @session_id.setter
    def session_id(self, value: str | None):
        cl.user_session.set(SESSION_ID, value)

    @property
    def history(self) -> list[dict[str, Any]]:
        return cl.user_session.get(SESSION_HISTORY) or []

    @history.setter
    def history(self, value: list[dict[str, Any]]):
        cl.user_session.set(SESSION_HISTORY, value)

    @property
    def character(self) -> str | None:
        return cl.user_session.get(SESSION_CHARACTER)

    @character.setter
    def character(self, value: str | None):
        cl.user_session.set(SESSION_CHARACTER, value)

    @property
    def persona_name(self) -> str | None:
        value = cl.user_session.get(SESSION_PERSONA_NAME)
        return value if isinstance(value, str) and value.strip() else None

    @persona_name.setter
    def persona_name(self, value: str | None):
        cl.user_session.set(SESSION_PERSONA_NAME, value)

    @property
    def scene(self) -> str | None:
        return cl.user_session.get(SESSION_SCENE)

    @scene.setter
    def scene(self, value: str | None):
        cl.user_session.set(SESSION_SCENE, value)

    @property
    def connection_id(self) -> str | None:
        return cl.user_session.get(SESSION_CONNECTION_ID)

    @connection_id.setter
    def connection_id(self, value: str | None):
        cl.user_session.set(SESSION_CONNECTION_ID, value)

    @property
    def query_params(self) -> dict[str, Any]:
        return cl.user_session.get(SESSION_QUERY_PARAMS) or {}

    @query_params.setter
    def query_params(self, value: dict[str, Any]):
        cl.user_session.set(SESSION_QUERY_PARAMS, value)

    @property
    def session_ended(self) -> bool:
        return bool(cl.user_session.get(SESSION_SESSION_ENDED))

    @session_ended.setter
    def session_ended(self, value: bool):
        cl.user_session.set(SESSION_SESSION_ENDED, value)

    @property
    def intro_pending(self) -> bool:
        return bool(cl.user_session.get(SESSION_INTRO_PENDING))

    @intro_pending.setter
    def intro_pending(self, value: bool):
        cl.user_session.set(SESSION_INTRO_PENDING, value)

    @property
    def local_intro_seen(self) -> bool:
        """Check if intro was seen in current browser session."""
        return bool(cl.user_session.get(SESSION_INTRO_SEEN))

    @local_intro_seen.setter
    def local_intro_seen(self, value: bool):
        cl.user_session.set(SESSION_INTRO_SEEN, value)

    def get_user_identifier(self) -> str | None:
        user = self.user
        return user.identifier if user else None
