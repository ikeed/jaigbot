import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.module_types import BrandingSpec, DialogueRoles, ModuleManifest
from app.routes.system import create_system_router


def _settings(**overrides):
    values = {
        "PROJECT_ID": "project",
        "REGION": "us-west4",
        "VERTEX_LOCATION": "global",
        "MODEL_ID": "gemini-test",
        "TEMPERATURE": 0.2,
        "MAX_TOKENS": 1024,
        "LOG_LEVEL": "INFO",
        "LOG_HEADERS": False,
        "LOG_REQUEST_BODY_MAX": 512,
        "LOG_RESPONSE_PREVIEW_MAX": 256,
        "ALLOWED_ORIGINS": [],
        "EXPOSE_UPSTREAM_ERROR": False,
        "DEBUG_MODE": False,
        "APP_ENV": "local",
        "gcs_object_prefix": "env=local",
        "MODEL_FALLBACKS": ["fallback"],
        "AUTO_CONTINUE_ON_MAX_TOKENS": True,
        "MAX_CONTINUATIONS": 2,
        "SUPPRESS_VERTEXAI_DEPRECATION": True,
        "AIMS_COACHING_ENABLED": True,
        "AIMS_COACHING_DEFAULT": False,
        "USE_VERTEX_REST": True,
        "CONTINUE_TAIL_CHARS": 500,
        "CONTINUE_INSTRUCTION_ENABLED": True,
        "MIN_CONTINUE_GROWTH": 10,
        "MEMORY_ENABLED": True,
        "MEMORY_BACKEND": "memory",
        "MEMORY_MAX_TURNS": 8,
        "MEMORY_TTL_SECONDS": 3600,
        "redis_key_prefix": "aims:local:session:",
        "redis_fallback_prefixes": [],
        "SESSION_COOKIE_NAME": "sid",
        "SESSION_COOKIE_SECURE": False,
        "SESSION_COOKIE_SAMESITE": "lax",
        "SESSION_COOKIE_MAX_AGE": 3600,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _client(*, settings=None, store=None, model_check=None, logger=None):
    app = FastAPI()
    memory_store = {} if store is None else store
    active_module = SimpleNamespace(
        manifest=ModuleManifest(
            id="aims",
            display_name="AIMS",
            chat_profile_name="AIMSBot",
            archive_schema_version="aims-v1",
            storage_prefix="aims:local:session:",
            dialogue_roles=DialogueRoles(participant_roles=("user", "assistant")),
            frontend_js_bundles=(
                "/public/js/aimsbot/message-roles.js",
                "/public/js/modules/aims/module-ui.js",
            ),
            branding=BrandingSpec(app_title="AIMSBot (Gemini Enterprise)"),
        )
    )
    app.include_router(
        create_system_router(
            settings=settings or _settings(),
            logger=logger or logging.getLogger("test.routes.system"),
            get_memory_store=lambda: memory_store,
            get_model_check=lambda: model_check or {"available": True},
            get_active_module=lambda: active_module,
            get_request_id=lambda request: request.headers.get("x-request-id"),
        )
    )
    return TestClient(app), memory_store


def test_history_filters_malformed_working_history_items():
    client, store = _client(
        store={
            "sid": {
                "history": [
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": 123},
                    "not-a-dict",
                    {"role": "coach", "content": "hint"},
                ],
                "full_history": [{"role": "user", "content": "hello", "time": 1}],
            }
        }
    )

    response = client.get("/history", params={"sessionId": "sid"})

    assert response.status_code == 200
    assert response.json() == {
        "history": [
            {"role": "user", "content": "hello"},
            {"role": "coach", "content": "hint"},
        ]
    }
    assert store["sid"]["full_history"][0]["time"] == 1


def test_history_full_and_disabled_memory_paths():
    client, _ = _client(
        settings=_settings(MEMORY_ENABLED=False),
        store={"sid": {"full_history": [{"role": "user", "content": "hello", "time": 1}]}},
    )

    assert client.get("/history", params={"sessionId": "sid", "full": True}).json() == {"history": []}

    client, _ = _client(
        store={"sid": {"full_history": [{"role": "user", "content": "hello", "time": 1}]}}
    )
    assert client.get("/history", params={"sessionId": "sid", "full": True}).json() == {
        "history": [{"role": "user", "content": "hello", "time": 1}]
    }


def test_history_returns_empty_when_memory_store_raises():
    logger = MagicMock()

    class RaisingStore(dict):
        def get(self, key, default=None):
            raise RuntimeError("store down")

    client, _ = _client(store=RaisingStore(), logger=logger)

    assert client.get("/history", params={"sessionId": "sid"}).json() == {"history": []}
    logger.error.assert_called_once()


def test_config_modelcheck_and_diagnostics_use_injected_dependencies():
    client, _ = _client(
        model_check={"available": False, "reason": "missing"},
        store={"a": {}, "b": {}},
    )

    config = client.get("/config").json()
    assert config["modelAvailable"] is False
    assert config["modelCheck"]["reason"] == "missing"
    assert config["memoryStoreSize"] == 2
    assert config["activeModule"]["id"] == "aims"
    assert config["activeModule"]["frontendJsBundles"] == [
        "/public/js/aimsbot/message-roles.js",
        "/public/js/modules/aims/module-ui.js",
    ]
    assert config["activeModule"]["branding"]["appTitle"] == "AIMSBot (Gemini Enterprise)"

    modelcheck = client.get("/modelcheck").json()
    assert modelcheck["modelId"] == "gemini-test"
    assert modelcheck["available"] is False

    diagnostics = client.get("/diagnostics").json()
    assert diagnostics["memory"]["storeSize"] == 2
    assert diagnostics["environment"]["gcsObjectPrefix"] == "env=local"
    assert diagnostics["environment"]["activeModuleId"] == "aims"


def test_models_success_uses_global_vertex_host(monkeypatch):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "models": [
                    {
                        "name": "publishers/google/models/gemini-test",
                        "displayName": "Gemini Test",
                        "supportedActions": {"generateContent": True},
                    }
                ]
            }

    session = MagicMock()
    session.get.return_value = FakeResponse()
    monkeypatch.setattr("google.auth.default", lambda scopes: ("creds", "project"))
    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", lambda creds: session)
    client, _ = _client()

    response = client.get("/models", headers={"x-request-id": "req-1"})

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {
                "id": "gemini-test",
                "displayName": "Gemini Test",
                "supportedActions": {"generateContent": True},
            }
        ],
        "count": 1,
        "region": "global",
    }
    assert "https://aiplatform.googleapis.com/" in session.get.call_args.args[0]


def test_models_non_200_maps_to_502(monkeypatch):
    session = MagicMock()
    session.get.return_value = SimpleNamespace(status_code=403)
    monkeypatch.setattr("google.auth.default", lambda scopes: ("creds", "project"))
    monkeypatch.setattr("google.auth.transport.requests.AuthorizedSession", lambda creds: session)
    client, _ = _client(settings=_settings(VERTEX_LOCATION="us-west4"))

    response = client.get("/models", headers={"x-request-id": "req-2"})

    assert response.status_code == 502
    assert response.json()["error"]["requestId"] == "req-2"
    assert "https://us-west4-aiplatform.googleapis.com/" in session.get.call_args.args[0]


def test_models_exception_maps_to_500(monkeypatch):
    monkeypatch.setattr("google.auth.default", MagicMock(side_effect=RuntimeError("adc missing")))
    client, _ = _client()

    response = client.get("/models", headers={"x-request-id": "req-3"})

    assert response.status_code == 500
    assert response.json() == {
        "error": {"message": "Internal server error", "code": 500, "requestId": "req-3"}
    }
