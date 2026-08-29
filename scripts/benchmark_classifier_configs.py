"""Compare AIMS classifier configurations on labelled turns from the repo's own suites.

Answers one question: does thinking_level="minimal" change classification quality on
gemini-3.6-flash, and what does it buy in latency?

Ground truth comes from the transcript replay suites and the benchmark script, so the
labels are the same ones CI already asserts on. Both configurations see byte-identical
inputs, so the head-to-head comparison is fair even where a simulated prior_phase is
imperfect.

Usage:
    PYTHONPATH=. .venv/bin/python bench_thinking.py --repeat 3
"""

from __future__ import annotations

import argparse
import asyncio
import os
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests" / "integration"))

from app.services.classifier_service import ClassifierService  # noqa: E402


# --------------------------------------------------------------------------- cases
@dataclass
class Case:
    name: str
    source: str
    person_last: str
    clinician_last: str
    history: list[dict[str, str]]
    prior_announced: bool
    prior_phase: str
    accept_steps: set[str] | None = None      # any of these atomic-step sets is correct
    expected_atoms: set[str] | None = None    # subset semantics (benchmark script style)
    not_steps: set[str] = field(default_factory=set)
    min_score: int | None = None
    max_score: int | None = None

    def judge(self, step: str, steps: set[str], score: int | None) -> tuple[bool, str]:
        """Return (correct, reason) using the same semantics the source suite uses."""
        if step in self.not_steps:
            return False, f"disallowed step {step!r}"
        if self.accept_steps is not None:
            if step not in self.accept_steps:
                return False, f"{step!r} not in accepted {sorted(self.accept_steps)}"
        if self.expected_atoms is not None:
            if not self.expected_atoms.issubset(steps):
                return False, f"missing atoms {sorted(self.expected_atoms - steps)}"
        if score is not None:
            if self.min_score is not None and score < self.min_score:
                return False, f"score {score} < {self.min_score}"
            if self.max_score is not None and score > self.max_score:
                return False, f"score {score} > {self.max_score}"
        return True, ""


_PHASE_AFTER_ANNOUNCE = "Inquire"


def _simulate_phase(prev_phase: str, prev_steps: set[str] | None) -> tuple[str, bool]:
    """Best-effort forward simulation when a suite does not record phase_after."""
    if not prev_steps:
        return prev_phase, prev_phase != "PreAnnounce"
    if "Announce" in prev_steps and prev_phase == "PreAnnounce":
        return _PHASE_AFTER_ANNOUNCE, True
    return prev_phase, prev_phase != "PreAnnounce"


def _atoms(step: str | None) -> set[str]:
    if not step:
        return set()
    return {p.strip() for p in str(step).split("+") if p.strip()}


def _from_transcript(cls: Any, source: str) -> list[Case]:
    cases: list[Case] = []
    turns = list(cls.CLINICIAN_TURNS)
    replies = list(cls.PARENT_REPLIES)
    expected = list(getattr(cls, "EXPECTED", []))
    history: list[dict[str, str]] = []
    phase = cls.INITIAL_AIMS_STATE.get("phase", "PreAnnounce")
    announced = bool(cls.INITIAL_AIMS_STATE.get("announced", False))

    if cls.INITIAL_PARENT_MSG:
        history.append({"role": "assistant", "content": cls.INITIAL_PARENT_MSG})

    for i, clinician in enumerate(turns):
        person_last = cls.INITIAL_PARENT_MSG if i == 0 else (replies[i - 1] if i - 1 < len(replies) else "")
        exp = expected[i] if i < len(expected) else None

        accept: set[str] | None = None
        not_steps: set[str] = set()
        min_s = max_s = None
        if exp is not None:
            if exp.accept_steps:
                accept = {s for s in exp.accept_steps if s}
                if not accept:
                    accept = None
            elif exp.step:
                accept = {exp.step}
            not_steps = set(exp.not_steps or [])
            min_s, max_s = exp.min_score, exp.max_score

        cases.append(Case(
            name=f"{source}#{i + 1}",
            source=source,
            person_last=person_last or "",
            clinician_last=clinician,
            history=list(history),
            prior_announced=announced,
            prior_phase=phase,
            accept_steps=accept,
            not_steps=not_steps,
            min_score=min_s,
            max_score=max_s,
        ))

        # advance context for the next turn
        history.append({"role": "user", "content": clinician})
        if i < len(replies):
            history.append({"role": "assistant", "content": replies[i]})
        expected_atoms = set()
        if exp is not None:
            usable = sorted(s for s in (exp.accept_steps or []) if s)
            expected_atoms = _atoms(exp.step) or (_atoms(usable[0]) if usable else set())
            if exp.phase_after:
                phase = exp.phase_after
                announced = phase != "PreAnnounce"
                continue
        phase, announced = _simulate_phase(phase, expected_atoms)

    return cases


def collect_cases() -> list[Case]:
    cases: list[Case] = []

    # 1. Transcript replay suites (importable class attributes).
    # tests/ is not a package, so register a synthetic one whose __path__ points at
    # tests/integration; that lets the sophia modules' `from .base import ...` resolve.
    import importlib
    import types
    if "aimsint" not in sys.modules:
        pkg = types.ModuleType("aimsint")
        pkg.__path__ = [str(REPO_ROOT / "tests" / "integration")]
        sys.modules["aimsint"] = pkg

    for modname, source in [
        ("test_transcript_ethan", "ethan"),
        ("test_transcript_jasmine", "jasmine"),
        ("aimsint.test_transcript_sophia", "sophia"),
        ("aimsint.test_transcript_sophia_deferred", "sophia_def"),
    ]:
        try:
            mod = importlib.import_module(modname)
        except Exception as e:  # noqa: BLE001
            print(f"  ! skipped {modname}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        import inspect
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if getattr(obj, "CLINICIAN_TURNS", None) and obj.__module__ == mod.__name__:
                cases.extend(_from_transcript(obj, source))

    # 2. The existing benchmark scenarios (subset semantics)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "bench_src", str(REPO_ROOT / "scripts" / "benchmark_classifier_models.py"))
        bs = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bs)
        for sc in bs.SCENARIOS:
            cases.append(Case(
                name=f"bench#{sc['name']}", source="benchmark",
                person_last=sc["person_last"], clinician_last=sc["clinician_last"],
                history=list(sc.get("history") or []),
                prior_announced=sc["prior_announced"], prior_phase=sc["prior_phase"],
                expected_atoms=set(sc["expected_steps"]),
            ))
    except Exception as e:  # noqa: BLE001
        print(f"  ! skipped benchmark scenarios: {type(e).__name__}: {e}", file=sys.stderr)

    # 3. Decision-boundary cases lifted from tests/integration/test_live_prompt_borderlines.py
    cases.extend([
        Case(name="borderline#closing_offer", source="borderline",
             person_last="I think that's everything, thanks for explaining it all.",
             clinician_last=("Of course. If anything else comes up before your next visit, "
                             "just call the clinic and we can talk it through."),
             history=[], prior_announced=True, prior_phase="Secure",
             accept_steps={"Secure", "Secure+Inquire"}, not_steps={"Inquire"}),
        Case(name="borderline#announce_with_question", source="borderline",
             person_last="",
             clinician_last=("Dakota is due for the HPV vaccine today, which prevents several "
                             "cancers. How are you feeling about that?"),
             history=[], prior_announced=False, prior_phase="PreAnnounce",
             accept_steps={"Announce+Inquire", "Announce"}, not_steps={"Inquire"}),
        Case(name="borderline#reflect_then_ask", source="borderline",
             person_last="I'm worried it's too many shots at once for her little body.",
             clinician_last=("So you're concerned that several vaccines together might overwhelm "
                             "her immune system. What have you read about that?"),
             history=[], prior_announced=True, prior_phase="Inquire",
             accept_steps={"Mirror+Inquire", "Mirror"}, not_steps={"Inquire"}),
        Case(name="borderline#evidence_after_mirror", source="borderline",
             person_last="Yes, that's exactly it. I just don't want to hurt her.",
             clinician_last=("That protective instinct makes complete sense. The studies we have "
                             "show the immune system handles these easily — can I share what they found?"),
             history=[], prior_announced=True, prior_phase="Mirror",
             accept_steps={"Mirror+Secure", "Secure", "Secure+Inquire", "Mirror+Secure+Inquire"}),
    ])

    # sophia and sophia_deferred are identical except for their final turn, so dedupe on
    # the actual model input to avoid double-weighting those turns in the accuracy figure.
    seen: set[tuple[str, str, str, bool]] = set()
    unique: list[Case] = []
    for c in cases:
        key = (c.clinician_last.strip(), c.person_last.strip(), c.prior_phase, c.prior_announced)
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return unique


# --------------------------------------------------------------------------- run
@dataclass
class Obs:
    case: str
    config: str
    step: str
    steps: set[str]
    score: int | None
    ms: int
    correct: bool
    reason: str
    error: str = ""


async def run_case(svc: ClassifierService, case: Case, config: str) -> Obs:
    t0 = time.perf_counter()
    try:
        res = await svc.classify_turn(
            clinician_message=case.clinician_last,
            person_last=case.person_last,
            history=case.history,
            mapping={},
            prior_announced=case.prior_announced,
            prior_phase=case.prior_phase,
        )
        ms = int((time.perf_counter() - t0) * 1000)
        aims = res.aims
        step = str(getattr(aims, "step", "") or "")
        steps = set(getattr(aims, "steps", None) or _atoms(step))
        score = getattr(aims, "score", None)
        ok, why = case.judge(step, steps, score)
        return Obs(case.name, config, step, steps, score, ms, ok, why)
    except Exception as e:  # noqa: BLE001
        ms = int((time.perf_counter() - t0) * 1000)
        return Obs(case.name, config, "", set(), None, ms, False, "error", f"{type(e).__name__}: {e}"[:200])


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=os.environ.get("PROJECT_ID", ""))
    ap.add_argument("--location", default="global")
    ap.add_argument("--model", default="gemini-3.6-flash")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--temperature", type=float, default=0.1)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", default="bench_classifier_configs.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="List the collected cases and exit without calling Vertex.")
    args = ap.parse_args()

    cases = collect_cases()
    if args.dry_run:
        for c in cases:
            label = (sorted(c.accept_steps) if c.accept_steps
                     else sorted(c.expected_atoms) if c.expected_atoms else ["<unlabelled>"])
            print(f"{c.name:<26} phase={c.prior_phase:<12} announced={str(c.prior_announced):<5} "
                  f"hist={len(c.history):<3} expect={label}")
        print(f"\n{len(cases)} cases")
        return 0
    if not args.project:
        print("--project (or PROJECT_ID) is required for a live run", file=sys.stderr)
        return 2
    print(f"Collected {len(cases)} labelled cases from "
          f"{len({c.source for c in cases})} sources: "
          f"{json.dumps({s: sum(1 for c in cases if c.source == s) for s in sorted({c.source for c in cases})})}")

    configs = {
        "default_thinking": None,   # what production runs today
        "minimal_thinking": "minimal",
    }
    services = {
        name: ClassifierService(
            project_id=args.project, location=args.location, model_id=args.model,
            temperature=args.temperature, max_tokens=args.max_tokens,
            thinking_level=level, thinking_budget=None,
        )
        for name, level in configs.items()
    }

    sem = asyncio.Semaphore(args.concurrency)

    async def guarded(svc, case, cfg):
        async with sem:
            return await run_case(svc, case, cfg)

    jobs = []
    for _rep in range(args.repeat):
        for cfg, svc in services.items():
            for case in cases:
                jobs.append(guarded(svc, case, cfg))

    print(f"Running {len(jobs)} live classifications "
          f"({len(cases)} cases x {len(configs)} configs x {args.repeat} repeats)...")
    t0 = time.perf_counter()
    obs: list[Obs] = list(await asyncio.gather(*jobs))
    print(f"done in {time.perf_counter() - t0:.1f}s\n")

    by_case = {c.name: c for c in cases}
    report(obs, by_case, list(configs))

    Path(args.out).write_text(json.dumps([
        {**o.__dict__, "steps": sorted(o.steps)} for o in obs
    ], indent=2))
    print(f"\nRaw observations written to {args.out}")
    return 0


def report(obs: list[Obs], by_case: dict[str, Case], configs: list[str]) -> None:
    print("=" * 78)
    print("ACCURACY AND LATENCY")
    print("=" * 78)
    print(f"{'config':<20} {'n':>5} {'errors':>7} {'correct':>9} {'acc':>7} "
          f"{'p50 ms':>8} {'p95 ms':>8} {'mean ms':>8}")
    summary = {}
    for cfg in configs:
        rows = [o for o in obs if o.config == cfg]
        errs = [o for o in rows if o.error]
        good = [o for o in rows if not o.error]
        lat = sorted(o.ms for o in good) or [0]
        correct = sum(1 for o in good if o.correct)
        acc = correct / len(good) if good else 0.0
        p50 = lat[len(lat) // 2]
        p95 = lat[max(0, int(len(lat) * 0.95) - 1)]
        summary[cfg] = (acc, p50, statistics.mean(lat))
        print(f"{cfg:<20} {len(rows):>5} {len(errs):>7} {correct:>9} {acc:>6.1%} "
              f"{p50:>8} {p95:>8} {statistics.mean(lat):>8.0f}")

    if len(configs) == 2:
        a, b = configs
        da = summary[a][0] - summary[b][0]
        dl = summary[a][2] - summary[b][2]
        print(f"\n{b} vs {a}: accuracy {-da:+.1%}, mean latency {-dl:+.0f} ms "
              f"({-dl / summary[a][2] * 100:+.0f}%)")

    print("\n" + "=" * 78)
    print("PER-CASE DISAGREEMENTS (majority step per config)")
    print("=" * 78)
    from collections import Counter, defaultdict
    per: dict[tuple[str, str], list[Obs]] = defaultdict(list)
    for o in obs:
        per[(o.case, o.config)].append(o)

    disagreements = 0
    for name in sorted(by_case):
        maj = {}
        for cfg in configs:
            rows = per.get((name, cfg), [])
            steps = [o.step for o in rows if not o.error]
            maj[cfg] = Counter(steps).most_common(1)[0][0] if steps else "<error>"
        if len({maj[c] for c in configs}) > 1:
            disagreements += 1
            case = by_case[name]
            exp = (sorted(case.accept_steps) if case.accept_steps
                   else sorted(case.expected_atoms) if case.expected_atoms else ["-"])
            print(f"  {name:<22} expected~{str(exp):<45}")
            for cfg in configs:
                rows = [o for o in per.get((name, cfg), []) if not o.error]
                ok = sum(1 for o in rows if o.correct)
                print(f"      {cfg:<18} -> {maj[cfg]:<26} correct {ok}/{len(rows)}")
    if not disagreements:
        print("  none — the two configurations produced the same majority step everywhere")
    else:
        print(f"\n  {disagreements} of {len(by_case)} cases disagree")

    print("\n" + "=" * 78)
    print("CASES FAILING UNDER EITHER CONFIG")
    print("=" * 78)
    any_fail = False
    for name in sorted(by_case):
        lines = []
        for cfg in configs:
            rows = [o for o in per.get((name, cfg), []) if not o.error]
            bad = [o for o in rows if not o.correct]
            if bad:
                lines.append(f"      {cfg:<18} {len(bad)}/{len(rows)} wrong: "
                             f"{bad[0].step!r} ({bad[0].reason})")
        if lines:
            any_fail = True
            print(f"  {name}")
            print("\n".join(lines))
    if not any_fail:
        print("  none")

    errs = [o for o in obs if o.error]
    if errs:
        print("\n" + "=" * 78)
        print(f"ERRORS ({len(errs)})")
        print("=" * 78)
        seen = Counter(o.error for o in errs)
        for msg, n in seen.most_common(10):
            print(f"  {n:>4}x {msg}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
