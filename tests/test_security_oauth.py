from app.security.oauth import get_enabled_oauth_providers, is_sso_configured


def _clear_oauth_client_ids(monkeypatch):
    import os

    for key in list(os.environ):
        if key.startswith("OAUTH_") and key.endswith("_CLIENT_ID"):
            monkeypatch.delenv(key, raising=False)


def test_get_enabled_oauth_providers_detects_well_known_and_dynamic(monkeypatch):
    _clear_oauth_client_ids(monkeypatch)
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setenv("OAUTH_AZURE_AD_CLIENT_ID", "azure-client")
    monkeypatch.setenv("OAUTH_MY_CUSTOM_PROVIDER_CLIENT_ID", "custom-client")

    providers = get_enabled_oauth_providers()

    assert {"id": "google", "name": "Google", "color": "#4285F4"} in providers
    assert {"id": "azure-ad", "name": "Microsoft", "color": "#00a1f1"} in providers
    assert {
        "id": "my-custom-provider",
        "name": "My-custom-provider",
        "color": "#6c757d",
    } in providers


def test_get_enabled_oauth_providers_ignores_invalid_and_duplicate_env(monkeypatch):
    _clear_oauth_client_ids(monkeypatch)
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_ID", "REPLACE_WITH_GOOGLE_CLIENT_ID")
    monkeypatch.setenv("OAUTH_GITHUB_CLIENT_ID", "")
    monkeypatch.setenv("OAUTH_OKTA_CLIENT_ID", "okta-client")
    monkeypatch.setenv("OAUTH_OKTA_CLIENT_SECRET", "not-a-client-id")

    providers = get_enabled_oauth_providers()

    provider_ids = [provider["id"] for provider in providers]
    assert provider_ids == ["okta"]


def test_is_sso_configured_reflects_enabled_provider_state(monkeypatch):
    _clear_oauth_client_ids(monkeypatch)
    assert is_sso_configured() is False

    monkeypatch.setenv("OAUTH_AUTH0_CLIENT_ID", "auth0-client")

    assert is_sso_configured() is True
