from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_ok():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_config_keys_present(monkeypatch):
    import app.main as m
    # Ensure PROJECT_ID not None to avoid surprises in later calls
    monkeypatch.setattr(m, "PROJECT_ID", "proj")

    r = client.get("/config")
    assert r.status_code == 200
    data = r.json()
    for key in [
        "projectId",
        "region",
        "modelId",
        "temperature",
        "maxTokens",
        "memoryEnabled",
        "memoryBackend",
        "memoryStoreSize",
        "sessionCookie",
    ]:
        assert key in data
    assert isinstance(data["sessionCookie"], dict)


def test_diagnostics_keys_present(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "PROJECT_ID", "proj")

    r = client.get("/diagnostics")
    assert r.status_code == 200
    data = r.json()
    assert "transport" in data
    assert "generationConfig" in data
    assert "memory" in data
    assert isinstance(data["memory"].get("storeSize"), int)
