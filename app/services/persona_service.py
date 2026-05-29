from __future__ import annotations

import copy
import hashlib
import json
import random
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

from app.config import DEFAULT_CHARACTER, DEFAULT_SCENE, settings


FALLBACK_PERSONA = {
    "name": "Jasmine",
    "brief": "A nervous first-time parent.",
    "detailed": "Jasmine is a nervous first-time parent worried about vaccine risks.",
    "scenario": {
        "visit_reason": "Well-baby check",
        "detailed_instructions": "Assure her of vaccine safety.",
        "user_sketch": "You are at the clinic for a well-baby checkup.",
        "vaccine_related": True,
    },
}


def _personas_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    return root / "prompts" / "personas.json"


@lru_cache(maxsize=1)
def _load_personas_cached() -> tuple[dict, ...]:
    try:
        data = json.loads(_personas_path().read_text(encoding="utf-8"))
        personas = data.get("personas") or []
        loaded = [p for p in personas if p.get("name")]
        return tuple(loaded or [FALLBACK_PERSONA])
    except Exception:
        return (FALLBACK_PERSONA,)


def load_personas() -> list[dict]:
    return copy.deepcopy(list(_load_personas_cached()))


def find_persona(name: str | None = None, persona_id: int | str | None = None) -> dict | None:
    personas = load_personas()
    if name:
        for persona in personas:
            if str(persona.get("name", "")).strip().lower() == str(name).strip().lower():
                return persona
    if persona_id is not None:
        for persona in personas:
            if str(persona.get("id")) == str(persona_id):
                return persona
    return None


def load_robust_persona(name: str | None = None) -> dict:
    if name:
        persona = find_persona(name=name)
        if persona:
            return persona

    personas = load_personas()
    if settings.PERSONA_INDEX is not None:
        try:
            idx = max(0, min(int(settings.PERSONA_INDEX), len(personas) - 1))
            return personas[idx]
        except Exception:
            pass
    return random.choice(personas) if personas else FALLBACK_PERSONA


def extract_persona_name_from_text(text: str | None) -> str | None:
    if not text:
        return None
    prefixes = (
        "Specific Persona:",
        "Persona:",
        "Person:",
        "Parent:",
        "Parent/Patient:",
    )
    for line in text.splitlines():
        stripped = line.strip()
        for prefix in prefixes:
            if stripped.startswith(prefix):
                return stripped.replace(prefix, "", 1).strip() or None
    return None


def extract_persona_name_from_archive(data: dict | None) -> str | None:
    if not isinstance(data, dict):
        return None
    persona = ((data.get("config") or {}).get("persona") or {})
    if isinstance(persona, dict):
        if persona.get("name"):
            return str(persona["name"])
        if persona.get("character"):
            name = extract_persona_name_from_text(persona.get("character"))
            if name:
                return name
    metadata = data.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("personaName"):
        return str(metadata["personaName"])
    return extract_persona_name_from_text(data.get("character"))


def _user_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.strip().lower().encode("utf-8")).hexdigest()


def persona_counts_key(user_id: str) -> str:
    return f"persona_counts:{_user_hash(user_id)}"


def persona_counted_key(user_id: str, session_id: str) -> str:
    digest = hashlib.sha256(f"{user_id.strip().lower()}:{session_id}".encode("utf-8")).hexdigest()
    return f"persona_counted:{digest}"


def _store_set(store: Any, key: str, value: dict, *, ttl: int = 0) -> None:
    setter = getattr(store, "set", None)
    if callable(setter):
        setter(key, value, ttl=ttl)
    else:
        store[key] = value


def get_cached_persona_counts(user_id: str, store: Any) -> dict[str, int] | None:
    value = store.get(persona_counts_key(user_id))
    if not isinstance(value, dict):
        return None
    counts = value.get("counts")
    if not isinstance(counts, dict):
        return None
    return {str(name): int(count or 0) for name, count in counts.items()}


def save_persona_counts(user_id: str, counts: dict[str, int], store: Any) -> None:
    _store_set(
        store,
        persona_counts_key(user_id),
        {"counts": counts, "updated": time.time(), "source": "redis"},
        ttl=0,
    )


def get_persona_counts(
    user_id: str | None,
    store: Any,
    *,
    load_counts: Callable[[str, Iterable[str]], dict[str, int]] | None = None,
) -> dict[str, int]:
    if not user_id:
        return {}
    cached = get_cached_persona_counts(user_id, store)
    if cached is not None:
        return cached
    personas = load_personas()
    valid_names = [str(p.get("name")) for p in personas if p.get("name")]
    counts = load_counts(user_id, valid_names) if load_counts else {}
    normalized = {name: int(counts.get(name, 0) or 0) for name in valid_names}
    save_persona_counts(user_id, normalized, store)
    return normalized


def choose_weighted_persona(personas: list[dict], counts: dict[str, int]) -> dict:
    if not personas:
        return FALLBACK_PERSONA
    weights = [1.0 / (int(counts.get(str(p.get("name")), 0) or 0) + 1.0) for p in personas]
    return random.choices(personas, weights=weights, k=1)[0]


def select_persona_for_user(
    user_id: str | None,
    store: Any,
    *,
    load_counts: Callable[[str, Iterable[str]], dict[str, int]] | None = None,
) -> dict:
    if settings.PERSONA_INDEX is not None:
        return load_robust_persona()
    personas = load_personas()
    counts = get_persona_counts(user_id, store, load_counts=load_counts)
    return choose_weighted_persona(personas, counts)


def record_persona_interaction_once(user_id: str | None, session_id: str, persona: dict, store: Any) -> bool:
    if not user_id or not session_id or not persona:
        return False
    marker_key = persona_counted_key(user_id, session_id)
    if store.get(marker_key):
        return False

    name = str(persona.get("name") or "").strip()
    if not name:
        return False
    counts = get_cached_persona_counts(user_id, store) or {}
    counts[name] = int(counts.get(name, 0) or 0) + 1
    save_persona_counts(user_id, counts, store)
    _store_set(store, marker_key, {"persona": name, "countedAt": time.time()}, ttl=0)
    return True


def _format_interaction_guidance(persona: dict) -> str:
    interaction = persona.get("interaction") or {}
    if not isinstance(interaction, dict):
        return ""

    lines: list[str] = []

    def add_list(label: str, key: str) -> None:
        values = interaction.get(key) or []
        if not values:
            return
        lines.append(f"{label}:")
        for value in values:
            cleaned = str(value).strip()
            if cleaned:
                lines.append(f"- {cleaned}")

    add_list("Communication needs", "communication_needs")
    add_list("Likely questions", "likely_questions")
    add_list("Avoid", "avoid")

    trust_repair = str(interaction.get("trust_repair") or "").strip()
    if trust_repair:
        lines.append(f"Trust repair: {trust_repair}")

    challenge = str(interaction.get("conversation_challenge") or "").strip()
    if challenge:
        lines.append(f"Conversation challenge: {challenge}")

    return "\n".join(lines)


def build_persona_session_fields(persona: dict) -> dict:
    base_char = settings.CHARACTER_SYSTEM or DEFAULT_CHARACTER
    base_scene = settings.SCENE_OBJECTIVES or DEFAULT_SCENE
    interaction_guidance = _format_interaction_guidance(persona)
    character = (
        f"{base_char}\n\n"
        f"Specific Persona: {persona['name']}\n"
        f"Detailed Biography and Motivations: {persona['detailed']}"
    )
    if interaction_guidance:
        character = f"{character}\n\nBehavioral Guidance:\n{interaction_guidance}"
    scene = (
        f"{base_scene}\n\n"
        f"Current Scenario: {persona['scenario']['visit_reason']}\n"
        f"Scenario Objectives: {persona['scenario']['detailed_instructions']}"
    )
    lines = [
        f"Person: {persona['name']}",
        f"Background: {persona['brief']}",
        f"Reason for visit: {persona['scenario']['user_sketch']}",
    ]
    is_pediatric = any(k in persona["brief"].lower() for k in ["parent", "child", "son", "daughter"])
    if not persona["scenario"].get("vaccine_related") and not is_pediatric:
        lines.append("\n(Note: You might want to mention vaccines during this visit.)")
    return {
        "character": character,
        "scene": scene,
        "initial_card": "\n".join(lines),
        "persona": {
            "id": persona.get("id"),
            "name": persona.get("name"),
        },
    }
