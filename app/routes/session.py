from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.constants import ENDPOINT_SESSION, ENDPOINT_DEREGISTER
from app.modules.aims.services.session_initializer import deregister_session_connection


class SessionInitRequest(BaseModel):
    sessionId: str
    connectionId: Optional[str] = None
    personaId: Optional[str] = None
    character: Optional[str] = None
    scene: Optional[str] = None
    userInfo: Optional[dict] = None
    initialCard: Optional[str] = None
    force: Optional[bool] = False


class SessionDeregisterRequest(BaseModel):
    sessionId: str
    connectionId: str


def create_session_router(
    *,
    settings: Any,
    logger: logging.Logger,
    get_memory_store: Callable[..., Any],
    get_active_module: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()

    @router.post(ENDPOINT_SESSION)
    async def init_session(
        body: SessionInitRequest,
        memory_store=Depends(get_memory_store),
        active_module=Depends(get_active_module),
    ):
        """Register a session in the memory store before chat messages arrive."""
        return active_module.initialize_session(
            body=body,
            memory_store=memory_store,
            memory_enabled=settings.MEMORY_ENABLED,
            logger=logger,
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
