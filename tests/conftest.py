import os
import sys
from unittest.mock import patch

import pytest

# Ensure project root is on sys.path for `import app.*`
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

INTEGRATION_DIR = os.path.join(os.path.dirname(__file__), "integration")


class LiveGeminiCallInTestError(RuntimeError):
    """Raised when a test outside tests/integration/ tries to open a real Vertex client."""


@pytest.fixture(autouse=True)
def block_live_gemini_clients(request, monkeypatch):
    """Fail loudly if a non-integration test constructs a real Gen AI client.

    The suite is supposed to be hermetic, but it was not: mocks were installed on some
    module-level ``GeminiClient`` names and not others, so any path that received the real
    class explicitly (app.main passes it as ``client_cls``) reached Vertex for real. That
    only ever surfaced for developers with Application Default Credentials configured —
    CI has none, so CI stayed green while the suite quietly spent tokens locally.

    Blocking ``genai.Client`` itself is deliberate: it is the single point where a network
    client is actually created, so this catches the mistake no matter which wrapper leaked.

    tests/integration/ is exempt; it is live by design and gated on the ``live_llm`` marker.
    """
    if str(request.node.fspath).startswith(INTEGRATION_DIR):
        yield []
        return

    violations: list[str] = []
    message = (
        "A real google.genai.Client was constructed in a non-integration test.\n"
        "This would make a live Vertex AI call and spend tokens.\n"
        "Patch the GeminiClient binding the code under test actually uses — note that "
        "app/main.py passes its own imported class through as client_cls — or move the "
        "test to tests/integration/ and mark it @pytest.mark.live_llm."
    )

    def _blocked(*args, **kwargs):
        # Record before raising. Much of the app wraps LLM calls in `except Exception`,
        # so raising alone can be swallowed and the test would still pass; the recorded
        # violation is re-raised at teardown where nothing can catch it.
        violations.append(f"project={kwargs.get('project')!r} location={kwargs.get('location')!r}")
        raise LiveGeminiCallInTestError(message)

    monkeypatch.setattr("google.genai.Client", _blocked)
    # app.gemini_client did `from google import genai`, so it resolves genai.Client at call time;
    # patching the attribute on that module object covers it. Guarded in case it changes.
    monkeypatch.setattr("app.gemini_client.genai.Client", _blocked, raising=False)

    # Yielded so a test that trips the guard deliberately (see
    # tests/unit/test_dependency_integrity.py) can clear the record and avoid failing
    # teardown. Ordinary tests never request this fixture by name.
    yield violations

    if violations:
        raise LiveGeminiCallInTestError(
            f"{message}\n\nAttempted client constructions: {violations}"
        )


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
    with (
        patch("app.aims_engine.load_mapping", return_value=mock_mapping),
        patch("app.aims_mapping_loader.load_mapping", return_value=mock_mapping),
    ):
        yield mock_mapping


@pytest.fixture(autouse=True)
def gemini_client_mock(monkeypatch):
    """
    Function-scoped auto-use fixture that mocks GeminiClient globally.
    This ensures that ClassifierService and other LLM callers use a safe mock
    instead of making real REST calls (which fail with 403 in tests).
    """
    import json

    # noinspection PyUnusedLocal
    class MockGeminiClient:
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
                return json.dumps({"patient_reply": "Mock patient reply from GeminiClient."})

            # 3. Default/Legacy fallback
            return json.dumps({"patient_reply": "Mock reply from GeminiClient."})

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

    # Rebinding app.gemini_client.GeminiClient does not retroactively change names already
    # imported elsewhere, so each importing module needs its own patch.
    #
    # app.main is the one that actually matters. _gemini_config() reads the module global
    # on every request and passes it as client_cls, which AimsCoachingHandler hands to
    # ClassifierService, and ClassifierService calls self.client_cls(...) in preference to
    # its own default. Missing app.main here is what let the suite reach live Vertex
    # whenever the developer had Application Default Credentials configured.
    #
    # Note that the classifier_service and gemini_helpers entries below are belt-and-braces
    # only: those modules bind GeminiClient as a *default argument*, which captures the
    # class object at import time, so monkeypatching the module attribute cannot reach it
    # (ClassifierService.__init__.__kwdefaults__["client_cls"] still points at the real
    # class afterwards). They are kept because the names are also read at runtime in some
    # paths, but do not rely on them to make a test hermetic — block_live_gemini_clients
    # above is the real backstop.
    for target in (
        "app.gemini_client.GeminiClient",
        "app.main.GeminiClient",
        "app.services.classifier_service.GeminiClient",
        "app.services.gemini_helpers.GeminiClient",
        "app.services.aims_coaching_handler.GeminiClient",
        "app.services.legacy_chat_handler.GeminiClient",
        "app.services.gemini_gateway.DefaultGeminiClient",
    ):
        monkeypatch.setattr(target, MockGeminiClient)
    return MockGeminiClient


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
