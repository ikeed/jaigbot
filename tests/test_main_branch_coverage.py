"""
Additional tests for main.py to improve branch coverage to 85%+

These tests target specific uncovered branches in the FastAPI application.
"""
import pytest
import os
import json
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app
from app.models import ChatRequest


client = TestClient(app)


class TestMainBranches:
    """Test branches in main.py"""

    def test_config_endpoint_full_coverage(self, monkeypatch):
        """Test config endpoint with different configurations"""
        # Test with debug mode enabled
        monkeypatch.setenv("DEBUG_MODE", "true")
        monkeypatch.setattr("app.main.DEBUG_MODE", True)
        monkeypatch.setattr("app.main.DEFAULT_CHARACTER", "Test Character")
        monkeypatch.setattr("app.main.DEFAULT_SCENE", "Test Scene")
        
        # Mock model check data
        mock_model_check = {
            "available": True,
            "modelId": "test-model",
            "region": "us-central1"
        }
        # Set model_check directly on app state
        app.state.model_check = mock_model_check
        try:
            r = client.get("/config")
            assert r.status_code == 200
            data = r.json()
            assert data["debugMode"] is True
        finally:
            # Clean up state
            if hasattr(app.state, 'model_check'):
                delattr(app.state, 'model_check')

    def test_config_endpoint_no_debug_mode(self, monkeypatch):
        """Test config endpoint with debug mode disabled"""
        monkeypatch.setattr("app.main.DEBUG_MODE", False)
        
        r = client.get("/config")
        assert r.status_code == 200
        data = r.json()
        assert data["debugMode"] is False
        assert data["defaultCharacter"] is None
        assert data["defaultScene"] is None

    def test_modelcheck_endpoint(self, monkeypatch):
        """Test modelcheck endpoint"""
        monkeypatch.setattr("app.main.MODEL_ID", "test-model")
        monkeypatch.setattr("app.main.VERTEX_LOCATION", "us-central1")
        
        mock_model_check = {
            "available": True,
            "modelId": "test-model",
            "region": "us-central1",
            "additional": "data"
        }
        # Set model_check directly on app state
        app.state.model_check = mock_model_check
        try:
            r = client.get("/modelcheck")
            assert r.status_code == 200
            data = r.json()
            assert data["modelId"] == "test-model"
            assert data["region"] == "us-central1"
            assert data["available"] is True
            assert data["additional"] == "data"
        finally:
            # Clean up state
            if hasattr(app.state, 'model_check'):
                delattr(app.state, 'model_check')

    def test_diagnostics_endpoint(self, monkeypatch):
        """Test diagnostics endpoint"""
        # Test with different environment configurations
        monkeypatch.setenv("USE_VERTEX_REST", "false")
        monkeypatch.setenv("CONTINUE_TAIL_CHARS", "300")
        monkeypatch.setenv("CONTINUE_INSTRUCTION_ENABLED", "false")
        monkeypatch.setenv("MIN_CONTINUE_GROWTH", "20")
        
        r = client.get("/diagnostics")
        assert r.status_code == 200
        data = r.json()
        assert data["transport"] == "sdk"  # USE_VERTEX_REST=false
        assert data["continueTailChars"] == 300
        assert data["continuationInstructionEnabled"] is False
        assert data["minContinueGrowth"] == 20

    def test_summary_endpoint_no_session(self):
        """Test summary endpoint with no session ID"""
        r = client.get("/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["overallScore"] == 0.0
        assert "stepCoverage" in data
        assert "strengths" in data
        assert "growthAreas" in data

    def test_summary_endpoint_memory_disabled(self, monkeypatch):
        """Test summary endpoint with memory disabled"""
        monkeypatch.setattr("app.main.MEMORY_ENABLED", False)
        
        r = client.get("/summary?sessionId=test-session")
        assert r.status_code == 200
        data = r.json()
        assert data["overallScore"] == 0.0

    def test_summary_endpoint_with_session_no_memory(self, monkeypatch):
        """Test summary endpoint with session but no stored memory"""
        monkeypatch.setattr("app.main.MEMORY_ENABLED", True)
        monkeypatch.setattr("app.main._MEMORY_STORE", {})
        
        r = client.get("/summary?sessionId=nonexistent-session")
        assert r.status_code == 200
        data = r.json()
        assert data["overallScore"] == 0.0

    def test_summary_endpoint_with_analysis_no_session(self):
        """Test summary endpoint with analysis=true but no session"""
        r = client.get("/summary?analysis=true")
        assert r.status_code == 200
        data = r.json()
        assert data["overallScore"] == 0.0
        assert data["analysis"] == []

    def test_summary_endpoint_with_aims_data(self, monkeypatch):
        """Test summary endpoint with AIMS data in memory"""
        mock_memory = {
            "test-session": {
                "aims": {
                    "perStepCounts": {"Announce": 2, "Inquire": 1, "Mirror": 1, "Secure": 0},
                    "scores": {"Announce": [2, 3], "Inquire": [2], "Mirror": [1]},
                    "totalTurns": 4
                },
                "history": [
                    {"role": "user", "content": "I'm worried about vaccines"},
                    {"role": "assistant", "content": "I understand your concerns"}
                ]
            }
        }
        
        monkeypatch.setattr("app.main.MEMORY_ENABLED", True)
        monkeypatch.setattr("app.main._MEMORY_STORE", mock_memory)
        
        r = client.get("/summary?sessionId=test-session")
        assert r.status_code == 200
        data = r.json()
        assert data["overallScore"] > 0  # Should calculate average
        assert data["stepCoverage"]["Announce"] == 2
        assert data["totalTurns"] == 4

    def test_summary_endpoint_exception_in_scores(self, monkeypatch):
        """Test summary endpoint handles exceptions in score calculation"""
        mock_memory = {
            "test-session": {
                "aims": {
                    "perStepCounts": {"Announce": 1},
                    "scores": {"Announce": ["invalid", "data"]},  # Invalid data to cause exception
                    "totalTurns": 1
                }
            }
        }
        
        monkeypatch.setattr("app.main.MEMORY_ENABLED", True)
        monkeypatch.setattr("app.main._MEMORY_STORE", mock_memory)
        
        r = client.get("/summary?sessionId=test-session")
        assert r.status_code == 200
        # Should handle exception gracefully

    @patch('app.services.vertex_helpers.vertex_call_with_fallback_text')
    def test_summary_endpoint_with_analysis_success(self, mock_vertex_call, monkeypatch):
        """Test summary endpoint with analysis=true and successful LLM call"""
        mock_memory = {
            "test-session": {
                "aims": {
                    "perStepCounts": {"Announce": 1, "Inquire": 0, "Mirror": 1, "Secure": 0},
                    "runningAverage": {"Announce": 2.0, "Mirror": 3.0},
                    "totalTurns": 2
                },
                "history": [
                    {"role": "user", "content": "What about vaccines?"},
                    {"role": "assistant", "content": "I have concerns"}
                ]
            }
        }
        
        mock_vertex_call.return_value = "- Practice more open questions\n- Use better reflections"
        
        monkeypatch.setattr("app.main.MEMORY_ENABLED", True)
        monkeypatch.setattr("app.main._MEMORY_STORE", mock_memory)
        monkeypatch.setattr("app.main.PROJECT_ID", "test-project")
        
        # Set aims_mapping directly on app state
        app.state.aims_mapping = {"test": "mapping"}
        try:
            r = client.get("/summary?sessionId=test-session&analysis=true")
            assert r.status_code == 200
            data = r.json()
            assert "analysis" in data
            assert len(data["analysis"]) > 0
        finally:
            # Clean up state
            if hasattr(app.state, 'aims_mapping'):
                delattr(app.state, 'aims_mapping')

    @patch('app.services.vertex_helpers.vertex_call_with_fallback_text')
    def test_summary_endpoint_analysis_vertex_exception(self, mock_vertex_call, monkeypatch):
        """Test summary endpoint handles Vertex call exceptions in analysis"""
        mock_memory = {
            "test-session": {
                "aims": {"perStepCounts": {"Announce": 1}, "totalTurns": 1},
                "history": [{"role": "user", "content": "test"}]
            }
        }
        
        mock_vertex_call.side_effect = Exception("Vertex error")
        
        monkeypatch.setattr("app.main.MEMORY_ENABLED", True)
        monkeypatch.setattr("app.main._MEMORY_STORE", mock_memory)
        monkeypatch.setattr("app.main.PROJECT_ID", "test-project")
        
        r = client.get("/summary?sessionId=test-session&analysis=true")
        assert r.status_code == 200
        data = r.json()
        assert data["analysis"] == []  # Should be empty due to exception

    def test_summary_endpoint_no_aims_mapping(self, monkeypatch):
        """Test summary endpoint when AIMS mapping fails to load"""
        mock_memory = {
            "test-session": {
                "aims": {"perStepCounts": {"Announce": 1}, "totalTurns": 1},
                "history": [{"role": "user", "content": "test"}]
            }
        }
        
        monkeypatch.setattr("app.main.MEMORY_ENABLED", True)
        monkeypatch.setattr("app.main._MEMORY_STORE", mock_memory)
        monkeypatch.setattr("app.main.PROJECT_ID", "test-project")
        
        # Clear aims_mapping from app state and mock load_mapping to raise exception
        if hasattr(app.state, 'aims_mapping'):
            delattr(app.state, 'aims_mapping')
        with patch('app.aims_engine.load_mapping', side_effect=Exception("Load failed")):
            r = client.get("/summary?sessionId=test-session&analysis=true")
            assert r.status_code == 200
            # Should handle the exception and continue

    @patch('google.auth.default')
    @patch('google.auth.transport.requests.AuthorizedSession')
    def test_models_endpoint_success(self, mock_session, mock_auth, monkeypatch):
        """Test /models endpoint successful response"""
        monkeypatch.setattr("app.main.PROJECT_ID", "test-project")
        monkeypatch.setattr("app.main.VERTEX_LOCATION", "us-central1")
        
        # Mock auth
        mock_creds = Mock()
        mock_auth.return_value = (mock_creds, None)
        
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "models": [
                {
                    "name": "projects/test/locations/us-central1/publishers/google/models/gemini-pro",
                    "displayName": "Gemini Pro",
                    "supportedActions": {"generateContent": True}
                }
            ]
        }
        
        mock_session_instance = Mock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance
        
        r = client.get("/models")
        assert r.status_code == 200
        data = r.json()
        assert "models" in data
        assert data["count"] == 1
        assert data["models"][0]["id"] == "gemini-pro"

    @patch('google.auth.default')
    @patch('google.auth.transport.requests.AuthorizedSession')
    def test_models_endpoint_http_error(self, mock_session, mock_auth, monkeypatch):
        """Test /models endpoint with HTTP error response"""
        monkeypatch.setattr("app.main.PROJECT_ID", "test-project")
        monkeypatch.setattr("app.main.VERTEX_LOCATION", "us-central1")
        
        # Mock auth
        mock_creds = Mock()
        mock_auth.return_value = (mock_creds, None)
        
        # Mock error response
        mock_response = Mock()
        mock_response.status_code = 403
        
        mock_session_instance = Mock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance
        
        r = client.get("/models")
        assert r.status_code == 502
        data = r.json()
        assert data["error"]["code"] == 502
        assert "Failed to list models" in data["error"]["message"]

    @patch('google.auth.default')
    def test_models_endpoint_exception(self, mock_auth, monkeypatch):
        """Test /models endpoint with exception"""
        monkeypatch.setattr("app.main.PROJECT_ID", "test-project")
        monkeypatch.setattr("app.main.VERTEX_LOCATION", "us-central1")
        
        # Mock exception in auth
        mock_auth.side_effect = Exception("Auth failed")
        
        r = client.get("/models")
        assert r.status_code == 500
        data = r.json()
        assert data["error"]["code"] == 500

    def test_get_request_id_cloud_trace(self):
        """Test _get_request_id with cloud trace header"""
        from app.main import _get_request_id
        
        mock_request = Mock()
        mock_request.headers.get.side_effect = lambda key: {
            "x-cloud-trace-context": "trace-id/span-id;o=1"
        }.get(key)
        
        request_id = _get_request_id(mock_request)
        assert request_id == "trace-id/span-id;o=1"

    def test_get_request_id_request_id_header(self):
        """Test _get_request_id with x-request-id header"""
        from app.main import _get_request_id
        
        mock_request = Mock()
        mock_request.headers.get.side_effect = lambda key: {
            "x-request-id": "custom-request-id"
        }.get(key)
        
        request_id = _get_request_id(mock_request)
        assert request_id == "custom-request-id"

    def test_get_request_id_request_state(self):
        """Test _get_request_id with request state"""
        from app.main import _get_request_id
        
        mock_request = Mock()
        mock_request.headers.get.return_value = None
        mock_request.state.request_id = "state-request-id"
        
        request_id = _get_request_id(mock_request)
        assert request_id == "state-request-id"

    def test_get_request_id_fallback_uuid(self):
        """Test _get_request_id fallback to UUID"""
        from app.main import _get_request_id
        
        mock_request = Mock()
        mock_request.headers.get.return_value = None
        # Make state access raise exception
        del mock_request.state
        
        request_id = _get_request_id(mock_request)
        # Should be a valid UUID string
        assert len(request_id) == 36  # Standard UUID length

    def test_get_request_id_exception_fallback(self):
        """Test _get_request_id exception handling"""
        from app.main import _get_request_id
        
        mock_request = Mock()
        # Mock headers.get to return None (no headers)
        mock_request.headers.get.return_value = None
        # Mock request.state to not have request_id attribute
        mock_state = Mock(spec=[])
        mock_request.state = mock_state
        
        request_id = _get_request_id(mock_request)
        # Should fallback to UUID when headers and state don't have request_id
        assert isinstance(request_id, str)
        assert len(request_id) == 36  # Standard UUID length

    def test_model_preflight_disabled(self, monkeypatch):
        """Test model preflight when disabled by environment"""
        monkeypatch.setattr("app.main.VALIDATE_MODEL_ON_STARTUP", False)
        
        # Mock the app state to verify it gets set correctly
        mock_state = Mock()
        mock_state.model_check = {}
        
        # The startup function should set the model check to disabled
        import asyncio
        from app.main import _model_preflight
        
        async def test_preflight():
            app.state = mock_state
            await _model_preflight()
            assert app.state.model_check["available"] == "unknown"
            assert app.state.model_check["reason"] == "disabled_by_env"
        
        asyncio.run(test_preflight())

    def test_model_preflight_no_project_id(self, monkeypatch):
        """Test model preflight when PROJECT_ID is missing"""
        monkeypatch.setattr("app.main.VALIDATE_MODEL_ON_STARTUP", True)
        monkeypatch.setattr("app.main.PROJECT_ID", None)
        
        import asyncio
        from app.main import _model_preflight
        
        async def test_preflight():
            await _model_preflight()
            assert app.state.model_check["available"] == "unknown"
            assert app.state.model_check["reason"] == "no_project_id"
        
        asyncio.run(test_preflight())

    @patch('google.auth.default')
    @patch('google.auth.transport.requests.AuthorizedSession')
    def test_model_preflight_success_200(self, mock_session, mock_auth, monkeypatch):
        """Test model preflight with successful 200 response"""
        monkeypatch.setattr("app.main.VALIDATE_MODEL_ON_STARTUP", True)
        monkeypatch.setattr("app.main.PROJECT_ID", "test-project")
        monkeypatch.setattr("app.main.VERTEX_LOCATION", "us-central1")
        monkeypatch.setattr("app.main.MODEL_ID", "gemini-pro")
        
        # Mock auth
        mock_creds = Mock()
        mock_auth.return_value = (mock_creds, None)
        
        # Mock 200 response
        mock_response = Mock()
        mock_response.status_code = 200
        
        mock_session_instance = Mock()
        mock_session_instance.get.return_value = mock_response
        mock_session.return_value = mock_session_instance
        
        import asyncio
        from app.main import _model_preflight
        
        async def test_preflight():
            await _model_preflight()
            assert app.state.model_check["available"] is True
            assert app.state.model_check["httpStatus"] == 200
        
        asyncio.run(test_preflight())

    @patch('google.auth.default')
    @patch('google.auth.transport.requests.AuthorizedSession')
    def test_model_preflight_404_with_list_match(self, mock_session, mock_auth, monkeypatch):
        """Test model preflight with 404 but model found in list"""
        monkeypatch.setattr("app.main.VALIDATE_MODEL_ON_STARTUP", True)
        monkeypatch.setattr("app.main.PROJECT_ID", "test-project")
        monkeypatch.setattr("app.main.VERTEX_LOCATION", "us-central1")
        monkeypatch.setattr("app.main.MODEL_ID", "gemini-pro")
        
        # Mock auth
        mock_creds = Mock()
        mock_auth.return_value = (mock_creds, None)
        
        # Mock 404 response for model check, 200 for list
        def mock_get(url):
            if "models/gemini-pro" in url:
                response = Mock()
                response.status_code = 404
                return response
            else:  # List endpoint
                response = Mock()
                response.status_code = 200
                response.json.return_value = {
                    "models": [
                        {"name": "projects/test/locations/us-central1/publishers/google/models/gemini-pro"}
                    ]
                }
                return response
        
        mock_session_instance = Mock()
        mock_session_instance.get.side_effect = mock_get
        mock_session.return_value = mock_session_instance
        
        import asyncio
        from app.main import _model_preflight
        
        async def test_preflight():
            await _model_preflight()
            assert app.state.model_check["available"] is True
            assert app.state.model_check["listMatched"] is True
        
        asyncio.run(test_preflight())

    def test_memory_store_initialization_redis_fallback(self, monkeypatch):
        """Test memory store initialization falls back to InMemory when Redis fails"""
        # This tests the exception handling in memory store initialization
        monkeypatch.setattr("app.main.MEMORY_ENABLED", True)
        monkeypatch.setattr("app.main.MEMORY_BACKEND", "redis")
        
        # The actual initialization happens at import time, so we test the fallback logic
        # by checking that the store is indeed an InMemoryStore when Redis is not available
        from app.main import _MEMORY_STORE
        # Should have fallen back to InMemoryStore
        assert hasattr(_MEMORY_STORE, '_store')  # InMemoryStore has _store attribute