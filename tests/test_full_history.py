"""
Tests for full_history, coach-aware history trimming, per-message timestamps,
and session_started / session_ended lifecycle fields.
"""
import asyncio
import logging
import time

from app.services.session_service import SessionService, CookieSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cookie():
    return CookieSettings(name="sid", secure=False, samesite="lax", max_age=3600)


def _svc(store=None, max_turns=3):
    return SessionService(
        store if store is not None else {},
        cookie=_cookie(),
        memory_enabled=True,
        memory_max_turns=max_turns,
        memory_ttl_seconds=3600,
    )


class _FakeRequest:
    cookies = {}


# ---------------------------------------------------------------------------
# _trim_history: coach-aware trimming
# ---------------------------------------------------------------------------

class TestTrimHistory:

    def test_no_trim_when_under_limit(self):
        hist = [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
        ]
        result = SessionService._trim_history(hist, max_turns=2)
        assert result == hist

    def test_trims_dialogue_only(self):
        """With max_turns=1, keep only the last user+assistant pair."""
        hist = [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ]
        result = SessionService._trim_history(hist, max_turns=1)
        assert len([m for m in result if m["role"] in ("user", "assistant")]) == 2
        assert result[-1]["content"] == "a2"
        assert result[-2]["content"] == "u2"

    def test_preserves_coach_entries_within_window(self):
        """Coach entries interleaved with the kept dialogue window survive trim."""
        hist = [
            {"role": "user", "content": "u1"},
            {"role": "coach", "content": "c1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "coach", "content": "c2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
            {"role": "coach", "content": "c3"},
            {"role": "assistant", "content": "a3"},
        ]
        # max_turns=2 → keep last 4 dialogue entries (u2,a2,u3,a3) + their coaches
        result = SessionService._trim_history(hist, max_turns=2)
        dialogue = [m for m in result if m["role"] in ("user", "assistant")]
        assert len(dialogue) == 4
        # Coach entries within the window should be kept
        coaches = [m for m in result if m["role"] == "coach"]
        assert len(coaches) == 2  # c2 and c3
        assert coaches[0]["content"] == "c2"
        assert coaches[1]["content"] == "c3"

    def test_drops_coach_entries_outside_window(self):
        """Coach entries before the kept window are dropped."""
        hist = [
            {"role": "coach", "content": "c0"},
            {"role": "user", "content": "u1"},
            {"role": "coach", "content": "c1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
        ]
        result = SessionService._trim_history(hist, max_turns=1)
        contents = [m["content"] for m in result]
        assert "c0" not in contents
        assert "c1" not in contents
        assert "u2" in contents
        assert "a2" in contents


# ---------------------------------------------------------------------------
# full_history: never trimmed, has timestamps
# ---------------------------------------------------------------------------

class TestFullHistory:

    def test_append_history_populates_full_history(self):
        store = {}
        svc = _svc(store, max_turns=2)
        sid, _ = svc.ensure_session(_FakeRequest(), None)

        svc.append_history(sid, "user", "hello")
        svc.append_history(sid, "assistant", "hi")
        svc.append_history(sid, "user", "q1")
        svc.append_history(sid, "assistant", "a1")
        svc.append_history(sid, "user", "q2")
        svc.append_history(sid, "assistant", "a2")

        mem = store[sid]
        # full_history has all 6 entries
        assert len(mem["full_history"]) == 6
        # history is trimmed to max_turns=2 → 4 dialogue entries
        dialogue = [m for m in mem["history"] if m["role"] in ("user", "assistant")]
        assert len(dialogue) == 4

    def test_full_history_entries_have_time(self):
        store = {}
        svc = _svc(store, max_turns=10)
        sid, _ = svc.ensure_session(_FakeRequest(), None)

        before = time.time()
        svc.append_history(sid, "user", "msg")
        after = time.time()

        fh = store[sid]["full_history"]
        assert len(fh) == 1
        assert "time" in fh[0]
        assert before <= fh[0]["time"] <= after

    def test_history_entries_do_not_have_time(self):
        """Trimmed history must stay clean {role, content} — no time field."""
        store = {}
        svc = _svc(store, max_turns=10)
        sid, _ = svc.ensure_session(_FakeRequest(), None)
        svc.append_history(sid, "user", "msg")

        for entry in store[sid]["history"]:
            assert "time" not in entry

    def test_coaching_handler_full_history(self):
        """Simulate the coaching handler flow: coach + user + assistant entries
        all appear in full_history with timestamps, while history is trimmed."""
        store = {}
        svc = _svc(store, max_turns=2)
        sid, _ = svc.ensure_session(_FakeRequest(), None)

        # Simulate 4 turns with coach entries (12 entries total)
        for i in range(4):
            now = time.time()
            mem = store[sid]
            # Coach entry (mirrors aims_coaching_handler inline append)
            coach_entry = {"role": "coach", "content": f"coach-{i}"}
            mem.setdefault("history", []).append(coach_entry)
            mem.setdefault("full_history", []).append({**coach_entry, "time": now})
            store[sid] = mem

            # User + assistant (mirrors _update_conversation_history)
            user_entry = {"role": "user", "content": f"u{i}"}
            asst_entry = {"role": "assistant", "content": f"a{i}"}
            mem["history"].append(user_entry)
            mem["history"].append(asst_entry)
            mem["full_history"].append({**user_entry, "time": now})
            mem["full_history"].append({**asst_entry, "time": now})
            mem["history"] = SessionService._trim_history(mem["history"], 2)
            store[sid] = mem

        mem = store[sid]
        # full_history: 4 turns × 3 entries = 12
        assert len(mem["full_history"]) == 12
        # history: trimmed to 2 turns of dialogue (4 user+assistant) + their coaches
        dialogue = [m for m in mem["history"] if m["role"] in ("user", "assistant")]
        assert len(dialogue) == 4
        # All full_history entries have time
        assert all("time" in e for e in mem["full_history"])
        # No history entries have time
        assert all("time" not in e for e in mem["history"])


# ---------------------------------------------------------------------------
# session_started / session_ended
# ---------------------------------------------------------------------------

class TestSessionTimestamps:

    def test_session_started_on_new_session(self):
        store = {}
        svc = _svc(store)
        before = time.time()
        sid, _ = svc.ensure_session(_FakeRequest(), None)
        after = time.time()

        mem = store[sid]
        assert "session_started" in mem
        assert before <= mem["session_started"] <= after

    def test_session_started_preserved_on_existing_session(self):
        """If session already exists, session_started should not be overwritten."""
        store = {}
        svc = _svc(store)
        sid, _ = svc.ensure_session(_FakeRequest(), None)
        original_started = store[sid]["session_started"]

        # Simulate a second ensure_session call (e.g. from a new request)
        time.sleep(0.01)
        svc.ensure_session(_FakeRequest(), sid)
        assert store[sid]["session_started"] == original_started

    def test_full_history_on_new_session(self):
        store = {}
        svc = _svc(store)
        sid, _ = svc.ensure_session(_FakeRequest(), None)
        assert "full_history" in store[sid]
        assert store[sid]["full_history"] == []


# ---------------------------------------------------------------------------
# Regression: the original bug scenario
# ---------------------------------------------------------------------------

class TestOriginalBugRegression:
    """Reproduce the exact scenario from the bug report: 11 turns with
    coach messages, MEMORY_MAX_TURNS=8.  Under the old logic (max_items=16),
    only ~5 turns survived.  With the fix, all 8 dialogue turn-pairs should
    be kept, plus their interleaved coaches."""

    def test_eleven_turns_keep_eight(self):
        store = {}
        svc = _svc(store, max_turns=8)
        sid, _ = svc.ensure_session(_FakeRequest(), None)

        # Simulate 11 turns with interleaved coach entries
        for i in range(11):
            now = time.time()
            mem = store[sid]
            # Coach
            coach_entry = {"role": "coach", "content": f"coach-{i}"}
            mem.setdefault("history", []).append(coach_entry)
            mem.setdefault("full_history", []).append({**coach_entry, "time": now})
            # User + assistant
            user_entry = {"role": "user", "content": f"doctor-{i}"}
            asst_entry = {"role": "assistant", "content": f"patient-{i}"}
            mem["history"].append(user_entry)
            mem["history"].append(asst_entry)
            mem["full_history"].append({**user_entry, "time": now})
            mem["full_history"].append({**asst_entry, "time": now})
            mem["history"] = SessionService._trim_history(mem["history"], 8)
            store[sid] = mem

        mem = store[sid]
        # full_history: all 11 × 3 = 33 entries
        assert len(mem["full_history"]) == 33

        # history: 8 dialogue turns (16 user+assistant) + their 8 coaches = 24
        dialogue = [m for m in mem["history"] if m["role"] in ("user", "assistant")]
        assert len(dialogue) == 16  # 8 turns × 2

        coaches = [m for m in mem["history"] if m["role"] == "coach"]
        assert len(coaches) == 8  # one per kept turn

        # The EARLIEST entries in trimmed history should be from turn 3 (0-indexed)
        assert dialogue[0]["content"] == "doctor-3"
        assert dialogue[1]["content"] == "patient-3"
