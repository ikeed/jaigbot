import os
import sys
from unittest.mock import patch

import pytest

# Ensure project root is on sys.path for `import app.*`
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture(scope="session", autouse=True)
def aims_mapping_mock():
    """
    Session-scoped auto-use fixture that mocks AIMS mapping to prevent Mock iteration errors.
    
    This fixture is applied to ALL tests automatically to ensure consistent
    behavior when classify_step() tries to access markers.get("Mirror", {}).get("linguistic", []).
    """
    import sys
    
    # Clear any cached modules that might have the old load_mapping
    modules_to_clear = [k for k in sys.modules.keys() if k.startswith('app.aims_engine')]
    for mod in modules_to_clear:
        if mod in sys.modules:
            del sys.modules[mod]
    
    mock_mapping = {
        "meta": {
            "per_step_classification_markers": {
                "Announce": {"linguistic": ["I recommend", "It's time for", "She/he is due for", "Today we will", "My recommendation is"]},
                "Inquire": {"linguistic": ["What concerns", "What have you heard", "What matters most", "How are you feeling about", "What would help"]},
                "Mirror": {"linguistic": ["It sounds like", "You're worried that", "I'm hearing", "You want", "You feel"]},
                "Secure": {"linguistic": ["It's your decision", "I'm here to support", "We can", "Options include", "If you'd prefer", "Here's what to expect"]}
            }
        }
    }
    
    # Use session-scoped patch
    with patch("app.aims_engine.load_mapping", return_value=mock_mapping):
        yield mock_mapping


@pytest.fixture(autouse=True)
def vertex_client_mock(monkeypatch):
    """
    Function-scoped auto-use fixture that mocks VertexClient globally.
    This ensures that ClassifierService and other LLM callers use a safe mock
    instead of making real REST calls (which fail with 403 in tests).
    """
    import json

    class MockVertexClient:
        def __init__(self, *args, **kwargs):
            self.project = kwargs.get("project")
            self.region = kwargs.get("region")
            self.model_id = kwargs.get("model_id")

        @staticmethod
        async def generate_text_async(prompt: str, **kwargs) -> str:
            # Also check system_instruction for classification detection
            sys_instr = (kwargs.get("system_instruction") or "").lower()
            # 1. Classification path (unified prompt or system-instruction-based)
            if "unified" in (prompt or "").lower() or "classify" in (prompt or "").lower() or "aims framework" in sys_instr:
                payload = {
                    "is_small_talk": False,
                    "is_vaccine_relevant": True,
                    "aims": {"step": "Inquire", "score": 3, "reasons": ["mock"], "tips": []},
                    "safety_flags": [],
                    "reasoning": "mock"
                }
                if "day going" in (prompt or "").lower():
                    payload["is_vaccine_relevant"] = False
                
                return json.dumps(payload)
            
            # 2. Patient reply path in coaching flow
            if "parent persona" in (prompt or "").lower() or "patient_reply" in (prompt or "").lower():
                # Avoid "ok" to prevent AimsCoachingHandler from overriding it with the long string
                return json.dumps({"patient_reply": "Mock patient reply from VertexClient."})

            # 3. Default/Legacy fallback
            return json.dumps({"patient_reply": "Mock reply from VertexClient."})

        @staticmethod
        def generate_text(*args, **kwargs):
            # If the first arg is prompt or prompt is in kwargs
            prompt = args[0] if args else kwargs.get("prompt", "")
            
            # Special case for test_chat_success_with_mock which expects "echo: "
            if isinstance(prompt, str) and prompt.startswith("User: "):
                user_msg = prompt.split("User: ")[-1].split("\n")[0].strip()
                return f"echo: {user_msg}", {}
            
            return "Mock text response", {}

        @staticmethod
        def generate_text_json(*args, **kwargs):
            return json.dumps({"patient_reply": "Mock JSON reply"})

    monkeypatch.setattr("app.vertex.VertexClient", MockVertexClient)
    monkeypatch.setattr("app.services.classifier_service.VertexClient", MockVertexClient)
    monkeypatch.setattr("app.services.vertex_helpers.VertexClient", MockVertexClient)
    return MockVertexClient


@pytest.fixture(autouse=True)
def clean_app_state():
    """
    Function-scoped auto-use fixture to clean up app.state.aims_mapping after each test
    to prevent pollution between tests.
    """
    import app.main
    
    # Store original state
    original_mapping = getattr(app.main.app.state, 'aims_mapping', None)
    
    yield
    
    # Clean up: reset to original state or delete if it wasn't there
    try:
        if original_mapping is not None:
            app.main.app.state.aims_mapping = original_mapping
        elif hasattr(app.main.app.state, 'aims_mapping'):
            delattr(app.main.app.state, 'aims_mapping')
    except Exception:
        # Don't let cleanup failures break tests
        pass
