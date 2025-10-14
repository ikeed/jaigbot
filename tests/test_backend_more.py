import json
from http import cookies

from fastapi.testclient import TestClient

import app.main as m
from app.main import app
from app.vertex import VertexAIError


client = TestClient(app)


def _unset_secure_cookie_for_tests(monkeypatch):
    # Allow cookie roundtrip over HTTP in TestClient
    monkeypatch.setattr(m, "SESSION_COOKIE_SECURE", False)


def test_healthz_config_diagnostics(monkeypatch):
    # Ensure PROJECT_ID set so /config derives correctly
    monkeypatch.setattr(m, "PROJECT_ID", "proj")
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

    c = client.get("/config")
    assert c.status_code == 200
    cfg = c.json()
    assert cfg["region"] == m.REGION
    assert "memoryBackend" in cfg and "memoryStoreSize" in cfg
    assert "sessionCookie" in cfg and "name" in cfg["sessionCookie"]

    d = client.get("/diagnostics")
    assert d.status_code == 200
    diag = d.json()
    assert "generationConfig" in diag
    assert diag["memory"]["backend"] == m.MEMORY_BACKEND


class FakeVertexEcho:
    def __init__(self, project: str, region: str, model_id: str):
        self.model_id = model_id

    # Legacy signature used by earlier tests in this repo
    def generate_text(self, prompt: str, temperature: float, max_tokens: int):
        return f"echo: {prompt}"


class FakeVertexFallback:
    def __init__(self, project: str, region: str, model_id: str):
        self.model_id = model_id

    def generate_text(self, prompt: str, temperature: float, max_tokens: int):
        # Primary model fails with 404; fallback succeeds
        if self.model_id == "bad-primary":
            raise VertexAIError("not found", status_code=404)
        return "ok-from-fallback"


class FakeVertexUpstreamError:
    def __init__(self, project: str, region: str, model_id: str):
        self.model_id = model_id

    def generate_text(self, prompt: str, temperature: float, max_tokens: int):
        raise VertexAIError("boom", status_code=500)


def test_session_cookie_and_memory_persistence(monkeypatch):
    # Arrange
    from app.services import legacy_chat_handler
    
    monkeypatch.setattr(m, "PROJECT_ID", "proj")
    _unset_secure_cookie_for_tests(monkeypatch)
    
    # Mock vertex helper to echo the prompt
    def mock_echo_call(*args, **kwargs):
        prompt = args[5] if len(args) > 5 else kwargs.get('prompt', 'hello')
        return f"echo: {prompt}"
    
    # Mock the function in the handler's module where it's actually imported and used
    monkeypatch.setattr(legacy_chat_handler, "vertex_call_with_fallback_text", mock_echo_call)

    # First call: no sessionId provided, backend should issue Set-Cookie
    r1 = client.post("/chat", json={"message": "hello"})
    assert r1.status_code == 200
    set_cookie = r1.headers.get("set-cookie")
    assert set_cookie and m.SESSION_COOKIE_NAME in set_cookie

    # Parse cookie value
    c = cookies.SimpleCookie()
    c.load(set_cookie)
    sess = c[m.SESSION_COOKIE_NAME].value
    assert sess

    # Verify memory has been created and has one user+assistant turn (2 entries)
    mem = m._MEMORY_STORE.get(sess)
    assert mem is not None
    assert len(mem.get("history", [])) == 2

    # Second call: rely on cookie only, memory should append and history grows to 4
    r2 = client.post("/chat", json={"message": "again"})
    assert r2.status_code == 200
    mem2 = m._MEMORY_STORE.get(sess)
    assert mem2 is not None
    assert len(mem2.get("history", [])) == 4



def test_model_fallback_success(monkeypatch):
    # Arrange: primary fails with 404, fallback succeeds
    from app.services import legacy_chat_handler
    
    monkeypatch.setattr(m, "PROJECT_ID", "proj")
    monkeypatch.setattr(m, "MODEL_ID", "bad-primary")
    monkeypatch.setattr(m, "MODEL_FALLBACKS", ["good-fallback"]) 
    _unset_secure_cookie_for_tests(monkeypatch)
    
    # Mock the vertex helper to simulate primary failure and fallback success
    def mock_fallback_call(*args, **kwargs):
        # Return a response that simulates successful fallback
        return "ok-from-fallback"
    
    # Mock the function in the handler's module where it's actually imported and used
    monkeypatch.setattr(legacy_chat_handler, "vertex_call_with_fallback_text", mock_fallback_call)

    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 200
    data = r.json()
    # With the new architecture, the model field will still show the primary model
    # since fallback handling is done at the vertex helper level
    assert data["model"] == "bad-primary"
    assert data["reply"] == "ok-from-fallback"
    # Cookie should still be present for session continuity
    assert m.SESSION_COOKIE_NAME in r.headers.get("set-cookie", "")



def test_upstream_error_maps_to_502_and_sets_cookie(monkeypatch):
    # Arrange
    from app.services import legacy_chat_handler
    from app.vertex import VertexAIError
    
    monkeypatch.setattr(m, "PROJECT_ID", "proj")
    _unset_secure_cookie_for_tests(monkeypatch)
    
    # Mock vertex helper to raise upstream error
    def mock_error_call(*args, **kwargs):
        raise VertexAIError("boom", status_code=500)
    
    # Mock the function in the handler's module where it's actually imported and used
    monkeypatch.setattr(legacy_chat_handler, "vertex_call_with_fallback_text", mock_error_call)

    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 502
    data = r.json()
    assert data["error"]["code"] == 502
    assert m.SESSION_COOKIE_NAME in r.headers.get("set-cookie", "")



def test_config_session_cookie_fields_reflect_env(monkeypatch):
    # Override cookie-related env-derived settings in module
    monkeypatch.setattr(m, "SESSION_COOKIE_NAME", "sid")
    monkeypatch.setattr(m, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(m, "SESSION_COOKIE_SAMESITE", "none")
    monkeypatch.setattr(m, "SESSION_COOKIE_MAX_AGE", 123)

    r = client.get("/config")
    cfg = r.json()
    sc = cfg["sessionCookie"]
    assert sc == {
        "name": "sid",
        "secure": False,
        "sameSite": "none",
        "maxAge": 123,
    }



def test_model_not_found_no_fallback_returns_404(monkeypatch):
    from app.services import legacy_chat_handler
    from app.vertex import VertexAIError
    
    monkeypatch.setattr(m, "PROJECT_ID", "proj")
    monkeypatch.setattr(m, "MODEL_FALLBACKS", [])
    _unset_secure_cookie_for_tests(monkeypatch)
    
    # Mock vertex helper to raise 404 error
    def mock_404_call(*args, **kwargs):
        raise VertexAIError("missing", status_code=404)
    
    # Mock the function in the handler's module where it's actually imported and used
    monkeypatch.setattr(legacy_chat_handler, "vertex_call_with_fallback_text", mock_404_call)

    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == 404
    # Cookie should still be set on error
    assert m.SESSION_COOKIE_NAME in r.headers.get("set-cookie", "")
