from fastapi.testclient import TestClient

from app.main import app
from app.vertex import VertexAIError

client = TestClient(app)


def test_model_fallback_succeeds(monkeypatch):
    import app.main as m

    primary = "primary-model"
    fallback = "fallback-model"

    monkeypatch.setattr(m, "PROJECT_ID", "proj")
    monkeypatch.setattr(m, "REGION", "us-central1")
    monkeypatch.setattr(m, "MODEL_ID", primary)
    monkeypatch.setattr(m, "MODEL_FALLBACKS", [fallback])

    class SwitchVertex:
        def __init__(self, project: str, region: str, model_id: str):
            self.model_id = model_id

        def generate_text(self, prompt: str, temperature: float, max_tokens: int):
            if self.model_id == primary:
                raise VertexAIError("not found", status_code=404)
            return "ok-from-fallback"

    # Mock at the VertexGateway level since this uses legacy chat path
    class SwitchGateway:
        def __init__(self, *args, primary_model=None, **kwargs):
            self.primary_model = primary_model or primary
            self.current_model = primary_model or primary
            self.last_model_used = None

        def generate_text(self, *args, **kwargs):
            log_fallback = kwargs.get('log_fallback')

            if self.current_model == primary:
                if log_fallback:
                    log_fallback(primary)
                self.current_model = fallback  # switch to fallback
                raise VertexAIError("not found", status_code=404)
            # If we get here, we're using the fallback model
            self.last_model_used = fallback
            return "ok-from-fallback"

        def generate_text_json(self, *args, **kwargs):
            return self.generate_text(*args, **kwargs)
    
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", SwitchGateway)

    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 200
    data = r.json()
    assert data["reply"] == "ok-from-fallback"
    # The endpoint reports the model actually used; should be the fallback id
    assert data["model"] == fallback


def test_upstream_error_maps_to_502_and_sets_cookie(monkeypatch):
    import app.main as m

    monkeypatch.setattr(m, "PROJECT_ID", "proj")
    monkeypatch.setattr(m, "REGION", "us-central1")
    monkeypatch.setattr(m, "MODEL_ID", "some-model")

    class ErrorVertex:
        def __init__(self, project: str, region: str, model_id: str):
            pass

        def generate_text(self, prompt: str, temperature: float, max_tokens: int):
            # Non-404 error should map to 502
            raise VertexAIError("upstream boom", status_code=503)

    # Mock at the VertexGateway level since this uses legacy chat path
    class ErrorGateway:
        def __init__(self, *args, **kwargs):
            pass
        
        def generate_text(self, *args, **kwargs):
            # Non-404 error should map to 502
            raise VertexAIError("upstream boom", status_code=503)
        
        def generate_text_json(self, *args, **kwargs):
            return self.generate_text(*args, **kwargs)
    
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", ErrorGateway)

    r = client.post("/chat", json={"message": "hello"})
    assert r.status_code == 502
    data = r.json()
    assert data["error"]["code"] == 502
    # Ensure cookie is still set so the client keeps a stable session
    assert "set-cookie" in {k.lower() for k in r.headers.keys()}
