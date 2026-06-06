from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data == {"status": "ok"}


def test_config_basic_shape():
    r = client.get("/config")
    assert r.status_code == 200
    cfg = r.json()

    # Expected keys
    for key in [
        "projectId",
        "region",
        "modelId",
        "temperature",
        "maxTokens",
        "logLevel",
        "logHeaders",
        "logRequestBodyMax",
        "allowedOrigins",
        "exposeUpstreamError",
        "modelFallbacks",
    ]:
        assert key in cfg, f"missing key {key} in /config response"

    # Types and defaults sanity
    assert isinstance(cfg["region"], str)
    assert isinstance(cfg["modelId"], str)
    assert isinstance(cfg["temperature"], (int, float))
    assert isinstance(cfg["maxTokens"], int)
    assert isinstance(cfg["logHeaders"], bool)
    assert isinstance(cfg["logRequestBodyMax"], int)
    assert isinstance(cfg["allowedOrigins"], list)
    assert isinstance(cfg["exposeUpstreamError"], bool)
    assert isinstance(cfg["modelFallbacks"], list)
