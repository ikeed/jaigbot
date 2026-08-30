from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from app.constants import ENDPOINT_DEREGISTER, ENDPOINT_SESSION
from app.services.session_initializer import (
    deregister_session_connection,
    initialize_session,
)


class SessionInitRequest(BaseModel):
    sessionId: str
    connectionId: str | None = None
    personaId: str | None = None
    character: str | None = None
    scene: str | None = None
    userInfo: dict | None = None
    initialCard: str | None = None
    force: bool | None = False


class SessionDeregisterRequest(BaseModel):
    sessionId: str
    connectionId: str


def create_session_router(
    *,
    settings: Any,
    logger: logging.Logger,
    get_memory_store: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()

    @router.post(ENDPOINT_SESSION)
    async def init_session(
        body: SessionInitRequest,
        background_tasks: BackgroundTasks,
        memory_store=Depends(get_memory_store),
    ):
        """Register a session in the memory store before chat messages arrive."""
        return initialize_session(
            body,
            memory_store=memory_store,
            memory_enabled=settings.MEMORY_ENABLED,
            logger=logger,
            background_tasks=background_tasks,
        )

    @router.post(ENDPOINT_DEREGISTER)
    async def deregister_session(body: SessionDeregisterRequest, memory_store=Depends(get_memory_store)):
        """Remove a connectionId from the active connections list."""
        return deregister_session_connection(
            body,
            memory_store=memory_store,
            memory_enabled=settings.MEMORY_ENABLED,
            logger=logger,
        )

    return router
