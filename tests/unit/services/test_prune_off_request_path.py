"""Session pruning must not run inline in the request.

prune_expired archives every expired session to GCS with a synchronous upload each.
ChatContextBuilder.build used to call it directly whenever ``int(time.time()) % 29 == 0``,
so roughly one request in 29 paid for an unbounded batch of blocking network calls on the
event loop, stalling every other in-flight request.

It is now flagged on the context and queued onto the request's BackgroundTasks, which
Starlette runs in a worker thread after the response is sent.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from app.services.chat_context import ChatContext, ChatContextBuilder
from app.services.session_service import _PRUNE_LOCK, SessionService


class _Sess:
    """Minimal SessionService stand-in that records whether prune was called."""

    def __init__(self):
        self.pruned = False

    def prune_expired(self):
        self.pruned = True

    def ensure_session(self, req, body_session_id, user_info=None):
        return ("sid", False)

    def get_mem(self, session_id):
        return {}

    def update_persona_scene(self, session_id, character, scene):
        return {}


def _builder(sess, mod):
    return ChatContextBuilder(
        session_service=sess,
        memory_enabled=False,
        memory_max_turns=8,
        memory_ttl_seconds=3600,
        do_prune_mod=mod,
    )


def test_build_flags_prune_but_never_runs_it(monkeypatch):
    """The builder must only report that a prune is due."""
    sess = _Sess()
    # mod=1 makes every request "due", removing the timing dependency.
    builder = _builder(sess, mod=1)

    ctx = builder.build(MagicMock(cookies={}), None, None, None, None)

    assert ctx.prune_due is True
    assert sess.pruned is False, (
        "ChatContextBuilder.build ran prune_expired inline; it must only set prune_due "
        "so the orchestrator can queue it as a background task."
    )


def test_build_does_not_flag_prune_when_not_due(monkeypatch):
    sess = _Sess()
    monkeypatch.setattr("app.services.chat_context.time.time", lambda: 100.0)
    # 100 % 7 != 0, so this turn is not a prune turn.
    builder = _builder(sess, mod=7)

    ctx = builder.build(MagicMock(cookies={}), None, None, None, None)

    assert ctx.prune_due is False
    assert sess.pruned is False


def test_chat_context_defaults_prune_due_to_false():
    """Existing tests construct ChatContext by keyword; the new field must be optional."""
    ctx = ChatContext(
        session_id="s",
        generated_session=False,
        mem={},
        effective_character=None,
        effective_scene=None,
        system_instruction=None,
        history_text="",
        person_last="",
    )
    assert ctx.prune_due is False


class TestPruneSingleFlight:
    """prune_expired now runs in a worker thread, so overlapping runs are possible."""

    @pytest.fixture(autouse=True)
    def _release_lock_afterwards(self):
        yield
        # Never leave the process-global lock held: every later prune would silently
        # no-op and mask unrelated failures.
        if _PRUNE_LOCK.locked():
            _PRUNE_LOCK.release()

    def test_second_concurrent_prune_is_skipped(self):
        from app.services.session_service import CookieSettings

        store = MagicMock()
        store.items.return_value = []
        svc = SessionService(
            store,
            cookie=CookieSettings(name="sid", secure=False, samesite="lax", max_age=0),
            memory_enabled=True,
            memory_max_turns=8,
            memory_ttl_seconds=1,
        )

        # Hold the lock as if a prune were already in flight in another thread.
        assert _PRUNE_LOCK.acquire(blocking=False)
        svc.prune_expired()
        _PRUNE_LOCK.release()

        store.items.assert_not_called()

    def test_prune_releases_the_lock_for_the_next_caller(self):
        from app.services.session_service import CookieSettings

        store = MagicMock()
        store.items.return_value = []
        svc = SessionService(
            store,
            cookie=CookieSettings(name="sid", secure=False, samesite="lax", max_age=0),
            memory_enabled=True,
            memory_max_turns=8,
            memory_ttl_seconds=1,
        )

        svc.prune_expired()
        svc.prune_expired()

        assert store.items.call_count == 2
        assert not _PRUNE_LOCK.locked()

    def test_lock_is_released_even_when_prune_raises(self):
        from app.services.session_service import CookieSettings

        store = MagicMock()
        store.items.side_effect = RuntimeError("store exploded")
        svc = SessionService(
            store,
            cookie=CookieSettings(name="sid", secure=False, samesite="lax", max_age=0),
            memory_enabled=True,
            memory_max_turns=8,
            memory_ttl_seconds=1,
        )

        svc.prune_expired()  # swallowed: prune is best-effort

        assert not _PRUNE_LOCK.locked(), (
            "prune_expired leaked the single-flight lock on failure; every later prune "
            "would silently no-op."
        )


def test_prune_lock_is_module_level_not_per_instance():
    """SessionService is constructed per request, so an instance lock would guard nothing."""
    assert isinstance(_PRUNE_LOCK, type(threading.Lock()))
