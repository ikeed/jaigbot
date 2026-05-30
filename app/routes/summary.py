from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Request

from app.services.summary_service import build_summary


def create_summary_router(
    *,
    settings: Any,
    logger: logging.Logger,
    get_memory_store: Callable[..., Any],
    vertex_client_cls: Any,
) -> APIRouter:
    router = APIRouter()

    @router.get("/summary")
    async def summary(
        request: Request,
        sessionId: Optional[str] = None,
        analysis: Optional[bool] = False,
        memory_store=Depends(get_memory_store),
    ):
        """Return an aggregated AIMS summary for a session."""
        return await build_summary(
            session_id=sessionId,
            analysis=bool(analysis),
            memory_store=memory_store,
            memory_enabled=settings.MEMORY_ENABLED,
            settings=settings,
            logger=logger,
            app_state=request.app.state,
            vertex_client_cls=vertex_client_cls,
        )

    return router
