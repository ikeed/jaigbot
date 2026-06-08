from __future__ import annotations

import json
import logging
from typing import Any

module_logger = logging.getLogger(__name__)


async def run_model_preflight(application: Any, *, settings: Any, logger: logging.Logger) -> None:
    """Best-effort check whether the configured Vertex model is visible.

    Stores tri-state availability in app.state.model_check and never raises.
    """
    application.state.model_check = {
        "available": "unknown",
        "modelId": settings.MODEL_ID,
        "region": settings.VERTEX_LOCATION,
    }
    if not settings.VALIDATE_MODEL_ON_STARTUP:
        application.state.model_check["reason"] = "disabled_by_env"
        return
    if not settings.PROJECT_ID:
        application.state.model_check["reason"] = "no_project_id"
        return

    try:
        import google.auth  # type: ignore
        from google.auth.transport.requests import AuthorizedSession  # type: ignore

        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = AuthorizedSession(creds)

        attempts: list[dict] = []

        def try_get(api_version: str) -> tuple[int, str]:
            loc = settings.VERTEX_LOCATION
            host = "aiplatform.googleapis.com" if str(loc).lower() == "global" else f"{loc}-aiplatform.googleapis.com"
            url = (
                f"https://{host}/{api_version}/projects/{settings.PROJECT_ID}"
                f"/locations/{loc}/publishers/google/models/{settings.MODEL_ID}"
            )
            response = session.get(url)
            attempts.append({"apiVersion": api_version, "url": url, "httpStatus": response.status_code})
            return response.status_code, url

        primary = "v1"
        code, url_primary = try_get(primary)
        application.state.model_check["apiVersion"] = primary
        application.state.model_check["urlPrimary"] = url_primary
        application.state.model_check["httpStatusPrimary"] = code

        if code == 404:
            check_models_list(application, settings=settings, session=session)
        else:
            application.state.model_check["httpStatus"] = code
            application.state.model_check["available"] = True if code == 200 else "unknown"

        application.state.model_check["urlsTried"] = attempts
        _set_generate_url(application, settings=settings)
    except Exception as exc:
        try:
            logger.info(json.dumps({
                "event": "model_preflight",
                "status": "exception",
                "error": str(exc),
                "modelId": settings.MODEL_ID,
                "region": settings.VERTEX_LOCATION,
            }))
        except Exception as log_exc:
            logger.info("model preflight error: %s (and logging failure: %s)", exc, log_exc)
        application.state.model_check["available"] = "unknown"
        application.state.model_check["error"] = str(exc)


def check_models_list(application: Any, *, settings: Any, session: Any) -> None:
    application.state.model_check["available"] = "unknown"
    loc = settings.VERTEX_LOCATION
    host = "aiplatform.googleapis.com" if str(loc).lower() == "global" else f"{loc}-aiplatform.googleapis.com"
    list_url = f"https://{host}/v1/projects/{settings.PROJECT_ID}/locations/{loc}/publishers/google/models"
    application.state.model_check["listUrl"] = list_url
    response = session.get(list_url)
    application.state.model_check["listHttpStatus"] = response.status_code

    matched = False
    if response.status_code == 200:
        try:
            data = response.json()
        except Exception as e:
            module_logger.debug("Failed to parse models list JSON: %s", e)
            data = {}
        models = data.get("models", []) or []
        application.state.model_check["listCount"] = len(models)
        matched = any((model.get("name", "").split("/models/")[-1]) == settings.MODEL_ID for model in models)

    application.state.model_check["listMatched"] = matched
    if matched:
        application.state.model_check["available"] = True


def _set_generate_url(application: Any, *, settings: Any) -> None:
    try:
        loc = settings.VERTEX_LOCATION
        host = "aiplatform.googleapis.com" if str(loc).lower() == "global" else f"{loc}-aiplatform.googleapis.com"
        gen_primary = "v1"
        base_gen_url = (
            f"https://{host}/{gen_primary}/projects/{settings.PROJECT_ID}"
            f"/locations/{loc}/publishers/google/models/{settings.MODEL_ID}:generateContent"
        )
        application.state.model_check["baseGenerateUrlPrimary"] = base_gen_url
    except Exception as e:
        module_logger.debug("Failed to construct base generate URL: %s", e)
