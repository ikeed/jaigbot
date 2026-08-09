from __future__ import annotations

from typing import Any

from app.constants import (
    KEY_AIMS_METRICS,
    KEY_AIMS_STATE,
    STEP_ANNOUNCE,
    STEP_ANNOUNCE_INQUIRE,
    STEP_INQUIRE,
    STEP_MIRROR,
    STEP_MIRROR_INQUIRE,
    STEP_MIRROR_SECURE,
    STEP_MIRROR_SECURE_INQUIRE,
    STEP_SECURE,
    STEP_SECURE_INQUIRE,
)


class AimsMetricsService:
    """Record and summarize per-session AIMS coaching metrics."""

    COMPOUND_EXPANSIONS: dict[str, list[str]] = {
        STEP_ANNOUNCE_INQUIRE: [STEP_ANNOUNCE, STEP_INQUIRE],
        STEP_MIRROR_INQUIRE: [STEP_MIRROR, STEP_INQUIRE],
        STEP_MIRROR_SECURE: [STEP_MIRROR, STEP_SECURE],
        STEP_SECURE_INQUIRE: [STEP_SECURE, STEP_INQUIRE],
        STEP_MIRROR_SECURE_INQUIRE: [STEP_MIRROR, STEP_SECURE, STEP_INQUIRE],
    }

    VALID_STEPS = frozenset({
        STEP_ANNOUNCE,
        STEP_INQUIRE,
        STEP_MIRROR,
        STEP_SECURE,
        *COMPOUND_EXPANSIONS.keys(),
    })

    def __init__(self, *, logger: Any) -> None:
        self._logger = logger

    @classmethod
    def component_steps(cls, step_current: str | None, steps: list[str] | None = None) -> list[str]:
        """Return de-duplicated atomic AIMS steps."""
        out: list[str] = []

        def add(component_name: str | None) -> None:
            if not component_name:
                return
            expanded = cls.COMPOUND_EXPANSIONS.get(component_name, [component_name])
            for item in expanded:
                if item and item not in out:
                    out.append(item)

        for item_name in steps or []:
            add(item_name)
        add(step_current)
        return out

    def persist(self, mem: dict[str, Any] | None, cls_payload: dict[str, Any]) -> None:
        """Update AIMS metrics in mem dict. Mutates mem in place."""
        if mem is None:
            return

        try:
            aims = mem.setdefault(KEY_AIMS_METRICS, {
                "perStepCounts": {s: 0 for s in self.VALID_STEPS},
                "scores": {s: [] for s in self.VALID_STEPS},
                "totalTurns": 0,
            })

            step = cls_payload.get("step")
            aims["totalTurns"] = int(aims.get("totalTurns", 0)) + 1

            if step in self.VALID_STEPS:
                score_val = int(cls_payload.get("score", 2))
                aims["perStepCounts"][step] = aims["perStepCounts"].get(step, 0) + 1
                aims["scores"].setdefault(step, []).append(score_val)

                for component in self.COMPOUND_EXPANSIONS.get(step, []):
                    aims["perStepCounts"][component] = aims["perStepCounts"].get(component, 0) + 1
                    aims["scores"].setdefault(component, []).append(score_val)

                aims["runningAverage"] = self._running_averages(aims)

            aims_state = mem.get(KEY_AIMS_STATE) or {}
            aims["secureBeforeMirrorCount"] = int(aims_state.get("secure_before_mirror_total", 0))

            mem[KEY_AIMS_METRICS] = aims

        except Exception as e:
            self._logger.debug(f"AIMS metrics update failed: {e}")

    def build_summary(self, mem: dict[str, Any] | None) -> dict[str, Any] | None:
        """Build session metrics snapshot from mem dict."""
        if mem is None:
            return None

        try:
            aims = mem.get(KEY_AIMS_METRICS) or {}
            counts = {s: 0 for s in self.VALID_STEPS}
            counts.update(aims.get("perStepCounts", {}))
            persona_value = mem.get("persona")
            persona: dict[str, Any] = persona_value if isinstance(persona_value, dict) else {}

            running_avg = aims.get("runningAverage") or {}
            if not running_avg:
                running_avg = self._running_averages(aims)

            return {
                "totalTurns": aims.get("totalTurns", 0),
                "perStepCounts": counts,
                "runningAverage": running_avg,
                "personaName": persona.get("name"),
                "patientName": persona.get("patient_name"),
                "secureBeforeMirrorCount": int(aims.get("secureBeforeMirrorCount", 0)),
            }

        except Exception as e:
            self._logger.debug(f"Failed to build session metrics: {e}")
            return None

    def _running_averages(self, aims: dict[str, Any]) -> dict[str, float]:
        averages: dict[str, float] = {}
        for key, scores in (aims.get("scores", {}) or {}).items():
            if not scores:
                continue
            try:
                averages[key] = float(sum(scores)) / len(scores)
            except Exception as e:
                self._logger.debug(f"Failed to calculate running average for {key}: {e}")
        return averages
