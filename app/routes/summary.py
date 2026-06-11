from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Request

from app.constants import ENDPOINT_SUMMARY


def create_summary_router(
    *,
    settings: Any,
    logger: logging.Logger,
    get_memory_store: Callable[..., Any],
    get_active_module: Callable[..., Any],
    vertex_client_cls: Any,
) -> APIRouter:
    router = APIRouter()

    @router.get(ENDPOINT_SUMMARY)
    async def summary(
        request: Request,
        sessionId: Optional[str] = None,
        analysis: Optional[bool] = False,
        memory_store=Depends(get_memory_store),
        active_module=Depends(get_active_module),
    ):
        """Return an aggregated module-owned summary for a session."""
        manifest = getattr(active_module, "manifest", None)
        if manifest is not None and not getattr(manifest, "supports_summary", False):
            return {"moduleId": getattr(active_module, "module_id", None), "supported": False}
        return await active_module.build_summary(
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
