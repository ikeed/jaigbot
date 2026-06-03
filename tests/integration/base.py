"""
Base infrastructure for live-LLM transcript replay integration tests.

Provides:
- ``ReplyOnlyGateway``: replaces VertexGateway to return scripted patient
  replies while letting classification flow through the real LLM.
- ``LiveClassifyClient``: wraps the real VertexClient but intercepts endgame
  prompts (returns non-endgame) to prevent premature session termination.
- ``TurnExpectation``: dataclass describing what the pipeline should produce
  for a given turn.
- ``TranscriptReplayTest``: base class that seeds a session, replays clinician
  turns through /chat, and asserts per-turn expectations against the real
  LLM + pipeline output.

Usage::

    @pytest.mark.live_llm
    class TestEthanTranscript(TranscriptReplayTest):
        SESSION_ID = "ethan-test"
        CLINICIAN_TURNS = [...]
        PARENT_REPLIES = [...]
        INITIAL_PARENT_MSG = ""
        INITIAL_AIMS_STATE = {...}
        EXPECTED = [TurnExpectation(step="Announce", min_score=2), ...]
"""
from __future__ import annotations

import copy
import json
import time
from dataclasses import dataclass, field
from typing import Optional

from fastapi.testclient import TestClient

import app.main as m
from app.vertex import VertexClient


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class ReplyOnlyGateway:
    """Drop-in replacement for VertexGateway that scripts patient replies.

    ``generate_text_json`` (used for patient reply generation) returns
    the next scripted reply from the list.  ``generate_text`` (used as a
    fallback path) is also intercepted.

    This class is instantiated once per ``vertex_call_with_fallback_*``
    invocation, so we use class-level state to track the reply index.
    """
    _replies: list[str] = []
    _reply_idx: int = 0

    @classmethod
    def reset(cls, replies: list[str]) -> None:
        cls._replies = list(replies)
        cls._reply_idx = 0

    def __init__(self, **kwargs) -> None:
        # Swallow all kwargs VertexGateway normally takes
        self.last_model_used = "scripted-reply"

    async def agenerate_text_json(self, *, prompt: str, **kwargs) -> str:
        idx = min(self._reply_idx, len(self._replies) - 1)
        ReplyOnlyGateway._reply_idx += 1
        return json.dumps({"patient_reply": self._replies[idx]})

    async def agenerate_text(self, prompt: str, **kwargs) -> str:
        # Fallback text path — return same scripted reply
        idx = min(self._reply_idx, len(self._replies) - 1)
        ReplyOnlyGateway._reply_idx += 1
        return json.dumps({"patient_reply": self._replies[idx]})

    def generate_text_json(self, *, prompt: str, **kwargs) -> str:
        idx = min(self._reply_idx, len(self._replies) - 1)
        ReplyOnlyGateway._reply_idx += 1
        return json.dumps({"patient_reply": self._replies[idx]})

    def generate_text(self, prompt: str, **kwargs) -> str:
        # Fallback text path — return same scripted reply
        idx = min(self._reply_idx, len(self._replies) - 1)
        ReplyOnlyGateway._reply_idx += 1
        return json.dumps({"patient_reply": self._replies[idx]})


class LiveClassifyClient(VertexClient):
    """VertexClient subclass that delegates to the real LLM for classification
    but optionally intercepts endgame detection prompts.

    By default, endgame calls are mocked to return ``is_endgame: false``.
    Set ``intercept_endgame = False`` to allow real LLM endgame detection.
    """
    intercept_endgame: bool = True

    _ENDGAME_RESPONSE = json.dumps({
        "is_endgame": False,
        "resolution_type": "not_resolved",
        "summary": "",
    })

    async def generate_text_async(self, prompt: str, **kwargs) -> str:
        if self.intercept_endgame and "endgame" in (prompt or "").lower():
            return self._ENDGAME_RESPONSE
        # Real LLM call for classification
        return await super().generate_text_async(prompt, **kwargs)


# ---------------------------------------------------------------------------
# Turn expectation
# ---------------------------------------------------------------------------

@dataclass
class TurnExpectation:
    """What the pipeline should produce for a single clinician turn.

    Fields set to ``None`` are not checked.  Use ``accept_steps`` when the
    LLM may reasonably return one of several steps (e.g. ``["Inquire",
    "Secure+Inquire"]``).
    """
    step: Optional[str] = None
    accept_steps: Optional[list[str]] = None
    min_score: Optional[int] = None
    max_score: Optional[int] = None
    not_steps: list[str] = field(default_factory=list)
    phase_after: Optional[str] = None
    is_endgame: Optional[bool] = None
    label: str = ""  # human-readable description for error messages


# ---------------------------------------------------------------------------
# Base test class
# ---------------------------------------------------------------------------

class TranscriptReplayTest:
    """Base class for live-LLM transcript replay integration tests.

    Subclasses define the transcript data and per-turn expectations as class
    attributes.  The base class provides:

    - ``_seed_session()`` — write initial AIMS state into the memory store
    - ``_post_turn()`` — POST a clinician message to /chat and return JSON
    - ``test_full_transcript_replay()`` — replay all turns, assert per-turn
    - ``test_full_history_completeness()`` — verify full_history is intact
    """

    # ---- Subclasses MUST set these ----
    SESSION_ID: str = ""
    CLINICIAN_TURNS: list[str] = []
    PARENT_REPLIES: list[str] = []
    INITIAL_PARENT_MSG: str = ""
    EXPECTED: list[TurnExpectation] = []

    # Initial AIMS state (override if the transcript starts mid-conversation).
    # Subclasses should override with a fresh dict; _seed_session copies it.
    INITIAL_AIMS_STATE: dict = {
        "announced": False,
        "phase": "PreAnnounce",
        "first_inquire_done": False,
        "pending_concerns": False,
        "parent_concerns": [],
        "mirrors_done": 0,
        "recent_coaching": [],
    }

    # Initial AIMS metrics (override to seed prior turn counts)
    INITIAL_AIMS_METRICS: dict = {
        "perStepCounts": {
            "Announce": 0, "Inquire": 0, "Mirror": 0, "Secure": 0,
            "Announce+Inquire": 0, "Mirror+Inquire": 0, "Mirror+Secure": 0,
            "Secure+Inquire": 0,
        },
        "scores": {
            "Announce": [], "Inquire": [], "Mirror": [], "Secure": [],
            "Announce+Inquire": [], "Mirror+Inquire": [], "Mirror+Secure": [],
            "Secure+Inquire": [],
        },
        "totalTurns": 0,
    }

    # ---- Helpers ----

    def _seed_session(self) -> None:
        """Write initial state into the memory store."""
        now = time.time()
        history = []
        full_history = []
        if self.INITIAL_PARENT_MSG:
            entry = {"role": "assistant", "content": self.INITIAL_PARENT_MSG}
            history.append(entry)
            full_history.append({**entry, "time": now})

        m.MEMORY_STORE[self.SESSION_ID] = {
            "history": history,
            "full_history": full_history,
            "character": None,
            "scene": None,
            "updated": now,
            "session_started": now,
            "aims_state": copy.deepcopy(self.INITIAL_AIMS_STATE),
            "aims": copy.deepcopy(self.INITIAL_AIMS_METRICS),
        }

    def _post_turn(self, client: TestClient, clinician_msg: str) -> dict:
        """POST a clinician turn and return parsed JSON."""
        r = client.post("/chat", json={
            "message": clinician_msg,
            "coach": True,
            "sessionId": self.SESSION_ID,
        })
        assert r.status_code == 200, f"Turn failed ({r.status_code}): {r.text}"
        return r.json()

    @staticmethod
    def _assert_turn(data: dict, exp: TurnExpectation, turn_num: int) -> None:
        """Assert a single turn's coaching output against expectations."""
        coaching = data.get("coaching", {})
        actual_step = coaching.get("step")
        actual_score = coaching.get("score")
        prefix = f"Turn {turn_num}"
        if exp.label:
            prefix = f"Turn {turn_num} ({exp.label})"

        # Step assertion
        if exp.accept_steps is not None:
            assert actual_step in exp.accept_steps, (
                f"{prefix}: expected step in {exp.accept_steps}, got {actual_step!r}"
            )
        elif exp.step is not None:
            assert actual_step == exp.step, (
                f"{prefix}: expected step={exp.step!r}, got {actual_step!r}"
            )

        # Negative step assertion
        for bad in (exp.not_steps or []):
            assert actual_step != bad, (
                f"{prefix}: step must NOT be {bad!r}, but got {actual_step!r}"
            )

        # Score range
        if exp.min_score is not None and actual_score is not None:
            assert actual_score >= exp.min_score, (
                f"{prefix}: expected score >= {exp.min_score}, got {actual_score}"
            )
        if exp.max_score is not None and actual_score is not None:
            assert actual_score <= exp.max_score, (
                f"{prefix}: expected score <= {exp.max_score}, got {actual_score}"
            )

        # Phase check requires SESSION_ID — handled in the test body.
        
        # Endgame assertion
        if exp.is_endgame is not None:
            actual_endgame = data.get("gameOver", False)
            assert actual_endgame == exp.is_endgame, (
                f"{prefix}: expected gameOver={exp.is_endgame}, got {actual_endgame}"
            )

    # ---- Standard test methods ----

    def test_full_transcript_replay(self) -> None:
        """Replay all clinician turns through the live LLM and check expectations."""
        ReplyOnlyGateway.reset(self.PARENT_REPLIES)
        self._seed_session()
        client = TestClient(m.app)

        assert len(self.EXPECTED) == len(self.CLINICIAN_TURNS), (
            f"EXPECTED has {len(self.EXPECTED)} entries but CLINICIAN_TURNS has "
            f"{len(self.CLINICIAN_TURNS)} — they must match 1:1"
        )

        results: list[dict] = []
        for i, msg in enumerate(self.CLINICIAN_TURNS):
            data = self._post_turn(client, msg)
            results.append(data)
            exp = self.EXPECTED[i]
            self._assert_turn(data, exp, i + 1)

            # Phase assertion (needs SESSION_ID context)
            if exp.phase_after is not None:
                state = m.MEMORY_STORE[self.SESSION_ID].get("aims_state", {})
                actual_phase = state.get("phase")
                prefix = f"Turn {i+1}"
                if exp.label:
                    prefix = f"Turn {i+1} ({exp.label})"
                assert actual_phase == exp.phase_after, (
                    f"{prefix}: expected phase={exp.phase_after!r} after turn, "
                    f"got {actual_phase!r}"
                )

    def test_full_history_completeness(self) -> None:
        """Verify full_history contains all entries and history is trimmed."""
        ReplyOnlyGateway.reset(self.PARENT_REPLIES)
        self._seed_session()
        client = TestClient(m.app)

        for msg in self.CLINICIAN_TURNS:
            self._post_turn(client, msg)

        mem = m.MEMORY_STORE[self.SESSION_ID]
        full = mem.get("full_history", [])
        trimmed = mem.get("history", [])

        n_turns = len(self.CLINICIAN_TURNS)
        full_dialogue = [e for e in full if e.get("role") in ("user", "assistant")]
        expected_initial = 1 if self.INITIAL_PARENT_MSG else 0
        expected_dialogue = n_turns * 2 + expected_initial
        assert len(full_dialogue) >= expected_dialogue, (
            f"full_history should have >= {expected_dialogue} user+assistant entries, "
            f"got {len(full_dialogue)}"
        )

        # All full_history entries have timestamps
        assert all("time" in e for e in full), (
            "All full_history entries must have a 'time' field"
        )

        # Trimmed history must NOT have timestamps
        assert all("time" not in e for e in trimmed), (
            "Trimmed history entries must NOT have a 'time' field"
        )
