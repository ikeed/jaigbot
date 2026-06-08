from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from app.models import ChatRequest, ReportRequest
from app.constants import ENDPOINT_CHAT, ENDPOINT_REPORT


def create_chat_router(
    *,
    settings: Any,
    get_chat_orchestrator: Callable[..., Any],
) -> APIRouter:
    router = APIRouter()

    @router.post(ENDPOINT_CHAT)
    async def chat(
        req: Request,
        body: ChatRequest,
        background_tasks: BackgroundTasks,
        orchestrator=Depends(get_chat_orchestrator),
    ):
        """Main chat endpoint using ChatOrchestrator."""
        if not settings.PROJECT_ID:
            raise HTTPException(status_code=500, detail={
                "error": {
                    "message": "settings.PROJECT_ID not set - configure the settings.PROJECT_ID environment variable.",
                    "code": 500,
                }
            })

        return await orchestrator.handle_chat(req, body, background_tasks)

    @router.post(ENDPOINT_REPORT)
    async def report(
        req: Request,
        body: ReportRequest,
        background_tasks: BackgroundTasks,
        orchestrator=Depends(get_chat_orchestrator),
    ):
        """Endpoint for reporting issues in a scenario."""
        return await orchestrator.handle_report(req, body, background_tasks)

    return router
