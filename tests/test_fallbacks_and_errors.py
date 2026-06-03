from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


def test_model_fallback_succeeds(monkeypatch):
    from app.vertex import VertexAIError
    import app.services.legacy_chat_handler
    import app.services.vertex_helpers
    import app.services.chat_orchestrator
    
    # Inject the exception class so it's available for catching
    app.services.legacy_chat_handler.VertexAIError = VertexAIError
    app.services.vertex_helpers.VertexAIError = VertexAIError
    app.services.chat_orchestrator.VertexAIError = VertexAIError

    primary = "primary-model"
    fallback = "fallback-model"

    monkeypatch.setattr(settings, "PROJECT_ID", "proj")
    monkeypatch.setattr(settings, "REGION", "us-central1")
    monkeypatch.setattr(settings, "MODEL_ID", primary)
    monkeypatch.setattr(settings, "MODEL_FALLBACKS", [fallback])
    monkeypatch.setattr(settings, "AIMS_COACHING_ENABLED", False)

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

        async def agenerate_text(self, *args, **kwargs):
            from app.vertex import VertexAIError
            log_fallback = kwargs.get('log_fallback')
            
            # Real gateway has an internal loop.
            models_to_try = [self.primary_model] + [fallback]
            last_err = None
            
            for mid in models_to_try:
                if mid == self.primary_model:
                    if log_fallback:
                        log_fallback(mid)
                    last_err = VertexAIError("not found", status_code=404)
                    continue
                
                # If we get here, we're using the fallback model
                self.last_model_used = mid
                return "ok-from-fallback"
            
            if last_err:
                raise last_err
            return "ok-from-fallback"

        async def agenerate_text_json(self, *args, **kwargs):
            return await self.agenerate_text(*args, **kwargs)

        def generate_text(self, *args, **kwargs):
            return "sync-not-used"

        def generate_text_json(self, *args, **kwargs):
            return "sync-not-used"
    
    monkeypatch.setattr("app.services.vertex_gateway.VertexGateway", SwitchGateway)

    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 200
    data = r.json()
    assert data["reply"] == "ok-from-fallback"
    # The endpoint reports the model actually used; should be the fallback id
    assert data["model"] == fallback


def test_upstream_error_maps_to_502_and_sets_cookie(monkeypatch):
    from app.vertex import VertexAIError
    import app.services.legacy_chat_handler
    import app.services.vertex_helpers
    import app.services.chat_orchestrator
    
    # Inject the exception class so it's available for catching
    app.services.legacy_chat_handler.VertexAIError = VertexAIError
    app.services.vertex_helpers.VertexAIError = VertexAIError
    app.services.chat_orchestrator.VertexAIError = VertexAIError

    monkeypatch.setattr(settings, "PROJECT_ID", "proj")
    monkeypatch.setattr(settings, "REGION", "us-central1")
    monkeypatch.setattr(settings, "MODEL_ID", "some-model")
    monkeypatch.setattr(settings, "AIMS_COACHING_ENABLED", False)

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
        
        async def agenerate_text(self, *args, **kwargs):
            from app.vertex import VertexAIError
            # Non-404 error should map to 502
            raise VertexAIError("upstream boom", status_code=503)

        async def agenerate_text_json(self, *args, **kwargs):
            return await self.agenerate_text(*args, **kwargs)

        def generate_text(self, *args, **kwargs):
            from app.vertex import VertexAIError
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
