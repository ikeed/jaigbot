from app.utils import env


def test_is_valid_env_val_rejects_empty_and_placeholder_values():
    assert env.is_valid_env_val(None) is False
    assert env.is_valid_env_val("") is False
    assert env.is_valid_env_val("  ") is False
    assert env.is_valid_env_val("REPLACE_WITH_CLIENT_ID") is False
    assert env.is_valid_env_val("your-id-here") is False
    assert env.is_valid_env_val("real-client-id") is True


def test_load_and_sanitize_env_strips_keys_values_and_quotes(monkeypatch):
    monkeypatch.setattr(env, "find_dotenv", lambda: "/tmp/.env")
    load_dotenv_calls = []
    monkeypatch.setattr(
        env,
        "load_dotenv",
        lambda *args, **kwargs: load_dotenv_calls.append((args, kwargs)),
    )
    monkeypatch.setenv("  OAUTH_GOOGLE_CLIENT_ID  ", '  "google-client"  ')
    monkeypatch.setenv("NORMAL_VALUE", " unchanged ")

    env.load_and_sanitize_env()

    assert load_dotenv_calls == [(("/tmp/.env",), {"override": True})]
    assert env.os.environ["OAUTH_GOOGLE_CLIENT_ID"] == "google-client"
    assert "  OAUTH_GOOGLE_CLIENT_ID  " not in env.os.environ
    assert env.os.environ["NORMAL_VALUE"] == "unchanged"


def test_load_and_sanitize_env_uses_default_loader_without_dotenv(monkeypatch):
    monkeypatch.setattr(env, "find_dotenv", lambda: "")
    load_dotenv_calls = []
    monkeypatch.setattr(
        env,
        "load_dotenv",
        lambda *args, **kwargs: load_dotenv_calls.append((args, kwargs)),
    )

    env.load_and_sanitize_env()

    assert load_dotenv_calls == [((), {})]
