from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.config import settings
from app.services.classifier_service import ClassifierService
from app.services.chat_helpers import recent_context
from app.services.prompt_builders import AimsPromptBuilder
from app.gemini_client import GeminiClient


SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "announce_inquire",
        "person_last": "",
        "clinician_last": (
            "Hi Georgina, I recommend the HPV vaccine for Dakota today because "
            "it prevents several cancers. What questions do you have?"
        ),
        "history": [],
        "prior_announced": False,
        "prior_phase": "PreAnnounce",
        "expected_steps": {"Announce", "Inquire"},
    },
    {
        "name": "mirror",
        "person_last": (
            "I'm just a bit worried about the side effects, especially for my "
            "daughter Dakota. I've heard some things."
        ),
        "clinician_last": (
            "It sounds like you're worried Dakota could have side effects from "
            "the HPV vaccine, especially because you've heard concerning things. "
            "Have I got that right?"
        ),
        "history": [
            {
                "role": "user",
                "content": (
                    "Hi Georgina, I recommend the HPV vaccine for Dakota today "
                    "because it prevents several cancers. What questions do you have?"
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "I'm just a bit worried about the side effects, especially for "
                    "my daughter Dakota. I've heard some things."
                ),
            },
        ],
        "prior_announced": True,
        "prior_phase": "InquireMirror",
        "expected_steps": {"Mirror"},
    },
    {
        "name": "secure_literature",
        "person_last": (
            "I still don't love the idea of doing it today, but I would read "
            "something and talk about it again."
        ),
        "clinician_last": (
            "That makes sense. You're the one deciding for Dakota, and I want you "
            "to feel comfortable. The HPV vaccine works best before exposure, "
            "which is why we offer it at this age. I can send you home with a "
            "one-page information sheet and we can revisit it next visit."
        ),
        "history": [],
        "prior_announced": True,
        "prior_phase": "Secure",
        "expected_steps": {"Secure"},
    },
]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        clean = value.strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _default_models() -> list[str]:
    return _dedupe(
        [
            settings.AIMS_CLASSIFIER_MODEL_ID,
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.6-flash",
            settings.MODEL_ID,
        ]
    )


def _scenario_prompt(scenario: dict[str, Any]) -> tuple[str, str]:
    system_instruction = AimsPromptBuilder.get_classify_system_instruction()
    prompt = AimsPromptBuilder.build_classify_turn_prompt(
        person_last=scenario["person_last"],
        clinician_last=scenario["clinician_last"],
        prior_announced=scenario["prior_announced"],
        prior_phase=scenario["prior_phase"],
        recent_context=recent_context(scenario.get("history") or [], 6),
        inquired_concerns_list=[],
        mirrored_concerns_list=[],
    )
    return prompt, system_instruction


def _detected_steps(aims: dict[str, Any]) -> set[str]:
    steps = aims.get("steps")
    if isinstance(steps, list) and steps:
        return {str(step) for step in steps if str(step or "").strip()}
    step = str(aims.get("step") or "").strip()
    return {part.strip() for part in step.split("+") if part.strip()}


async def _run_once(
    *,
    model_id: str,
    scenario: dict[str, Any],
    thinking_level: str | None,
    thinking_budget: int | None,
    max_tokens: int,
    timeout_s: float,
) -> dict[str, Any]:
    prompt, system_instruction = _scenario_prompt(scenario)
    client = GeminiClient(
        project=settings.PROJECT_ID,
        region=settings.VERTEX_LOCATION or settings.REGION,
        model_id=model_id,
    )
    config = client._build_config(
        temperature=0.1,
        max_tokens=max_tokens,
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=None,
        thinking_budget=thinking_budget,
        thinking_level=thinking_level,
    )

    started = time.perf_counter()
    try:
        response = await asyncio.wait_for(
            client._get_client().aio.models.generate_content(
                model=model_id,
                contents=prompt,
                config=config,
            ),
            timeout=timeout_s,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        text, meta = client._extract_response(response)
        parsed = json.loads(ClassifierService._strip_json_fences(text))
        aims = parsed.get("aims") or {}
        detected = _detected_steps(aims)
        expected = set(scenario["expected_steps"])
        return {
            "modelId": model_id,
            "scenario": scenario["name"],
            "ok": True,
            "elapsedMs": elapsed_ms,
            "step": aims.get("step"),
            "steps": sorted(detected),
            "expectedSteps": sorted(expected),
            "matchedExpected": expected.issubset(detected),
            "score": aims.get("score"),
            "feedbackItemCount": len(aims.get("feedback_items") or []),
            "finishReason": meta.get("finishReason"),
            "promptTokens": meta.get("promptTokens"),
            "candidatesTokens": meta.get("candidatesTokens"),
            "thoughtsTokens": meta.get("thoughtsTokens"),
            "cachedContentTokens": meta.get("cachedContentTokens"),
            "textLen": meta.get("textLen"),
        }
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "modelId": model_id,
            "scenario": scenario["name"],
            "ok": False,
            "elapsedMs": elapsed_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _run(args: argparse.Namespace) -> list[dict[str, Any]]:
    models = _dedupe(args.models or _default_models())
    results: list[dict[str, Any]] = []
    for model_id in models:
        for scenario in SCENARIOS:
            for _ in range(args.repeat):
                result = await _run_once(
                    model_id=model_id,
                    scenario=scenario,
                    thinking_level=args.thinking_level,
                    thinking_budget=args.thinking_budget,
                    max_tokens=args.max_tokens,
                    timeout_s=args.timeout,
                )
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
    return results


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark live Gemini model latency for the AIMS classifier prompt."
    )
    parser.add_argument(
        "--models",
        nargs="+",
        help="Model IDs to test. Defaults to configured classifier plus GA candidates.",
    )
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--thinking-level",
        default=settings.AIMS_CLASSIFIER_THINKING_LEVEL,
        choices=["minimal", "low", "medium", "high", "none"],
    )
    parser.add_argument(
        "--thinking-budget",
        type=int,
        default=settings.AIMS_CLASSIFIER_THINKING_BUDGET,
    )
    args = parser.parse_args()
    if args.thinking_level == "none":
        args.thinking_level = None
    return args


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
