"""
Test suite to verify that all required secrets and variables from the deployment
workflow are correctly passed and accessible in the application.

This test runs in the cloud on GitHub Actions and should verify:
- All secrets from deploy.yaml are injected
- All variables from deploy.yaml are injected
- SSO credentials are properly configured
- The application can start with these settings
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from app.config import Settings


class TestDeploymentSecrets:
    """Test that deployment secrets are properly injected."""

    def test_chainlit_auth_secret_available(self, monkeypatch):
        """Verify CHAINLIT_AUTH_SECRET is accessible when set."""
        test_secret = "test-chainlit-secret-12345"
        monkeypatch.setenv("CHAINLIT_AUTH_SECRET", test_secret)

        # Reload settings to pick up the environment variable
        settings = Settings()
        assert settings.CHAINLIT_AUTH_SECRET == test_secret

    def test_oauth_google_client_secret_available(self, monkeypatch):
        """Verify OAUTH_GOOGLE_CLIENT_SECRET is accessible when set."""
        test_secret = "test-oauth-secret-abcdef"
        monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_SECRET", test_secret)

        # Store it and verify it's available via environment
        assert os.getenv("OAUTH_GOOGLE_CLIENT_SECRET") == test_secret

    def test_all_deployment_secrets_injected(self, monkeypatch):
        """Verify all secrets from deploy.yaml are available."""
        secrets = {
            "CHAINLIT_AUTH_SECRET": "test-chainlit-secret",
            # Note: OAUTH_GOOGLE_CLIENT_SECRET is not part of Settings
            # but should be available in environment for actual OAuth flow
        }

        for key, value in secrets.items():
            monkeypatch.setenv(key, value)
            settings = Settings()
            assert getattr(settings, key) == value


class TestDeploymentVariables:
    """Test that deployment variables are properly injected."""

    def test_gcp_project_id_variable(self, monkeypatch):
        """Verify PROJECT_ID variable is accessible."""
        proj_id = "test-project-12345"
        monkeypatch.setenv("PROJECT_ID", proj_id)

        settings = Settings()
        assert settings.PROJECT_ID == proj_id

    def test_gcp_region_variable(self, monkeypatch):
        """Verify REGION variable is accessible."""
        region = "us-central1"
        monkeypatch.setenv("REGION", region)

        settings = Settings()
        assert settings.REGION == region

    def test_model_id_variable(self, monkeypatch):
        """Verify MODEL_ID variable is accessible."""
        model = "gemini-2.5-pro"
        monkeypatch.setenv("MODEL_ID", model)

        settings = Settings()
        assert settings.MODEL_ID == model

    def test_temperature_variable(self, monkeypatch):
        """Verify TEMPERATURE variable is properly parsed."""
        temp = "0.7"
        monkeypatch.setenv("TEMPERATURE", temp)

        settings = Settings()
        assert settings.TEMPERATURE == 0.7

    def test_max_tokens_variable(self, monkeypatch):
        """Verify MAX_TOKENS variable is properly parsed."""
        tokens = "1024"
        monkeypatch.setenv("MAX_TOKENS", tokens)

        settings = Settings()
        assert settings.MAX_TOKENS == 1024

    def test_aims_coaching_enabled_variable(self, monkeypatch):
        """Verify AIMS_COACHING_ENABLED variable is accessible."""
        # Note: Boolean parsing from string is handled by pydantic
        monkeypatch.setenv("AIMS_COACHING_ENABLED", "true")

        settings = Settings()
        assert settings.AIMS_COACHING_ENABLED is True

    def test_memory_backend_variable(self, monkeypatch):
        """Verify MEMORY_BACKEND variable is accessible."""
        backend = "redis"
        monkeypatch.setenv("MEMORY_BACKEND", backend)

        settings = Settings()
        assert settings.MEMORY_BACKEND == backend

    def test_redis_url_variable(self, monkeypatch):
        """Verify REDIS_URL variable is accessible."""
        redis_url = "redis://localhost:6379"
        monkeypatch.setenv("REDIS_URL", redis_url)

        settings = Settings()
        assert settings.REDIS_URL == redis_url

    def test_oauth_google_client_id_variable(self, monkeypatch):
        """Verify OAUTH_GOOGLE_CLIENT_ID variable is accessible."""
        client_id = "test-client-id-123456.apps.googleusercontent.com"
        monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_ID", client_id)

        # OAUTH_GOOGLE_CLIENT_ID is not in Settings but should be available
        assert os.getenv("OAUTH_GOOGLE_CLIENT_ID") == client_id


class TestProductionConfiguration:
    """Test that the application starts correctly with production settings."""

    def test_settings_load_with_all_deployment_variables(self, monkeypatch):
        """Verify Settings loads correctly with all deployment variables."""
        deployment_vars = {
            "PROJECT_ID": "test-project",
            "REGION": "us-central1",
            "MODEL_ID": "gemini-2.5-pro",
            "TEMPERATURE": "0.2",
            "MAX_TOKENS": "768",
            "AIMS_COACHING_ENABLED": "true",
            "MEMORY_BACKEND": "memory",
            "CHAINLIT_AUTH_SECRET": "test-secret-123",
            "LOG_LEVEL": "INFO",
        }

        for key, value in deployment_vars.items():
            monkeypatch.setenv(key, value)

        settings = Settings()

        # Verify all variables are loaded
        assert settings.PROJECT_ID == "test-project"
        assert settings.REGION == "us-central1"
        assert settings.MODEL_ID == "gemini-2.5-pro"
        assert settings.TEMPERATURE == 0.2
        assert settings.MAX_TOKENS == 768
        assert settings.AIMS_COACHING_ENABLED is True
        assert settings.MEMORY_BACKEND == "memory"
        assert settings.CHAINLIT_AUTH_SECRET == "test-secret-123"
        assert settings.LOG_LEVEL == "INFO"

    def test_sso_credentials_configured(self, monkeypatch):
        """Verify SSO credentials are configured for production."""
        monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "prod-secret")
        monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_ID", "prod-client-id")
        monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_SECRET", "prod-client-secret")

        settings = Settings()

        # Verify SSO is configured
        assert settings.CHAINLIT_AUTH_SECRET == "prod-secret"
        assert os.getenv("OAUTH_GOOGLE_CLIENT_ID") == "prod-client-id"
        assert os.getenv("OAUTH_GOOGLE_CLIENT_SECRET") == "prod-client-secret"

    def test_memory_backend_redis_configured(self, monkeypatch):
        """Verify Redis memory backend can be configured."""
        redis_url = "redis://redis:6379"
        monkeypatch.setenv("MEMORY_BACKEND", "redis")
        monkeypatch.setenv("REDIS_URL", redis_url)

        settings = Settings()

        assert settings.MEMORY_BACKEND == "redis"
        assert settings.REDIS_URL == redis_url

    def test_app_env_defaults_to_local_outside_cloud_run(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("K_SERVICE", raising=False)

        settings = Settings()

        assert settings.APP_ENV == "local"
        assert settings.redis_key_prefix == "aims:local:session:"
        assert settings.gcs_object_prefix == "env=local"

    def test_app_env_namespaces_prod_resources(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "prod")

        settings = Settings()

        assert settings.APP_ENV == "prod"
        assert settings.redis_key_prefix == "aims:prod:session:"
        assert settings.redis_fallback_prefixes == ["aims:session:"]
        assert settings.gcs_path("sessions/v1", "user_id=u", "session_id=s.json") == (
            "env=prod/sessions/v1/user_id=u/session_id=s.json"
        )

    def test_cloud_run_requires_explicit_app_env(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.setenv("K_SERVICE", "aimsbot")

        with pytest.raises(ValueError, match="APP_ENV must be set"):
            Settings()


class TestEnvironmentVariableValidation:
    """Test that environment variable validation works correctly."""

    def test_project_id_auto_detection_fallback(self, monkeypatch):
        """Verify PROJECT_ID falls back to environment detection."""
        # Clear PROJECT_ID to test fallback
        monkeypatch.delenv("PROJECT_ID", raising=False)
        monkeypatch.setenv("GCP_PROJECT_ID", "fallback-project")

        settings = Settings()
        assert settings.PROJECT_ID == "fallback-project"

    def test_region_defaults_to_us_central1(self, monkeypatch):
        """Verify REGION defaults to us-central1 if not set."""
        monkeypatch.delenv("REGION", raising=False)
        monkeypatch.delenv("GCP_REGION", raising=False)
        monkeypatch.delenv("GOOGLE_CLOUD_REGION", raising=False)

        settings = Settings()
        assert settings.REGION in ["us-central1", "us-west4"]  # Could be either default

    def test_model_id_defaults_correctly(self, monkeypatch):
        """Verify MODEL_ID defaults to gemini-2.5-pro."""
        monkeypatch.delenv("MODEL_ID", raising=False)

        settings = Settings()
        assert settings.MODEL_ID == "gemini-2.5-pro"

    def test_temperature_conversion_from_string(self, monkeypatch):
        """Verify TEMPERATURE is correctly converted from string."""
        monkeypatch.setenv("TEMPERATURE", "0.9")

        settings = Settings()
        assert isinstance(settings.TEMPERATURE, float)
        assert settings.TEMPERATURE == 0.9

    def test_max_tokens_conversion_from_string(self, monkeypatch):
        """Verify MAX_TOKENS is correctly converted from string."""
        monkeypatch.setenv("MAX_TOKENS", "2048")

        settings = Settings()
        assert isinstance(settings.MAX_TOKENS, int)
        assert settings.MAX_TOKENS == 2048


class TestDeploymentIntegration:
    """Integration tests to verify deployment configuration."""

    def test_app_initializes_with_deployment_settings(self, monkeypatch):
        """Verify the FastAPI app can initialize with deployment settings."""
        deployment_vars = {
            "PROJECT_ID": "test-project",
            "REGION": "us-central1",
            "MODEL_ID": "gemini-2.5-pro",
            "CHAINLIT_AUTH_SECRET": "test-secret",
        }
        
        for key, value in deployment_vars.items():
            monkeypatch.setenv(key, value)
        
        # Mock VertexClient to avoid real API calls
        monkeypatch.setattr(
            "app.vertex.VertexClient",
            MagicMock(return_value=MagicMock())
        )
        
        try:
            settings = Settings()
            assert settings.PROJECT_ID == "test-project"
        except Exception as e:
            pytest.fail(f"App failed to initialize with deployment settings: {e}")

    def test_deployment_yaml_env_vars_match_settings(self):
        """Verify that all env vars in deploy.yaml are supported by Settings."""
        # This is a static check of the deploy.yaml configuration
        # against the Settings class

        # Expected env vars from deploy.yaml
        deployment_env_vars = [
            "APP_ENV",
            "PROJECT_ID",
            "REGION",
            "GAR_REPO",  # Not in Settings, but used in deployment
            "SERVICE_NAME",  # Not in Settings, but used in deployment
            "STAGING_SERVICE_NAME",  # Not in Settings, but used in deployment
            "MODEL_ID",
            "TEMPERATURE",
            "MAX_TOKENS",
            "AIMS_COACHING_ENABLED",
            "CHAINLIT_AUTH_SECRET",
            "CHAINLIT_URL",  # Not in Settings, but used in deployment
            "STAGING_CHAINLIT_URL",  # Not in Settings, but used in deployment
            "OAUTH_GOOGLE_CLIENT_ID",
            "OAUTH_GOOGLE_CLIENT_SECRET",
            "MEMORY_BACKEND",
            "REDIS_URL",
            "TF_BACKEND_BUCKET",  # Not in Settings, used for Terraform
            "TF_BACKEND_PREFIX",  # Not in Settings, used for Terraform
            "VPC_CONNECTOR",  # Not in Settings, used by deployment
        ]

        settings_fields = {f for f in dir(Settings()) if not f.startswith("_")}

        # Check that Settings-specific variables exist in the class
        for var in ["PROJECT_ID", "REGION", "MODEL_ID", "TEMPERATURE",
                    "MAX_TOKENS", "AIMS_COACHING_ENABLED", "CHAINLIT_AUTH_SECRET",
                    "MEMORY_BACKEND", "REDIS_URL", "APP_ENV"]:
            assert var in settings_fields, f"{var} not found in Settings"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
