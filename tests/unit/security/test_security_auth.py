from pathlib import Path
from unittest.mock import MagicMock

from app.security import auth


def test_authenticated_user_identifier_returns_none_without_cookie(monkeypatch):
    request = MagicMock(cookies={})
    monkeypatch.setattr(auth, "get_token_from_cookies", lambda cookies: None)

    assert auth.authenticated_user_identifier(request) is None


def test_authenticated_user_identifier_returns_decoded_identifier(monkeypatch):
    request = MagicMock(cookies={"chainlit-auth": "token"})
    monkeypatch.setattr(auth, "get_token_from_cookies", lambda cookies: "token")
    monkeypatch.setattr(
        auth,
        "decode_jwt",
        lambda token: MagicMock(identifier="doctor@example.com"),
    )

    assert auth.authenticated_user_identifier(request) == "doctor@example.com"


def test_authenticated_user_identifier_returns_none_on_decode_failure(monkeypatch):
    request = MagicMock(cookies={"chainlit-auth": "token"})
    monkeypatch.setattr(auth, "get_token_from_cookies", lambda cookies: "token")

    def fail_decode(token):
        raise RuntimeError("bad token")

    monkeypatch.setattr(auth, "decode_jwt", fail_decode)

    assert auth.authenticated_user_identifier(request) is None


def test_clear_persistent_session_id_removes_user_specific_and_default_files(
    tmp_path, monkeypatch
):
    chainlit_dir = tmp_path / ".chainlit"
    chainlit_dir.mkdir()
    user_file = chainlit_dir / "session_id_doctor_example_com"
    default_file = chainlit_dir / "session_id"
    unrelated_file = chainlit_dir / "session_id_other"
    user_file.write_text("user-session")
    default_file.write_text("default-session")
    unrelated_file.write_text("other")
    clear_current_thread_id = MagicMock()
    monkeypatch.setattr(auth, "_get_chainlit_dir", lambda: str(chainlit_dir))
    monkeypatch.setattr(auth, "clear_current_thread_id", clear_current_thread_id)

    auth.clear_persistent_session_id("doctor@example.com")

    clear_current_thread_id.assert_called_once_with("doctor@example.com")
    assert not user_file.exists()
    assert not default_file.exists()
    assert unrelated_file.exists()


def test_clear_persistent_session_id_ignores_file_errors(monkeypatch):
    monkeypatch.setattr(auth, "_get_chainlit_dir", lambda: str(Path("/tmp/chainlit")))
    monkeypatch.setattr(auth, "clear_current_thread_id", MagicMock())
    monkeypatch.setattr(auth.os.path, "exists", lambda path: True)

    def fail_remove(path):
        raise OSError("permission denied")

    monkeypatch.setattr(auth.os, "remove", fail_remove)

    auth.clear_persistent_session_id("doctor@example.com")
