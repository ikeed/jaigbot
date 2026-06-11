from __future__ import annotations

import logging
import time
from typing import Any

from app.chat_roles import ROLE_ASSISTANT, ROLE_SYSTEM, is_scenario_card
from app.modules.aims.services.persona_service import (
    build_persona_session_fields,
    extract_persona_name_from_text,
    find_persona,
    record_persona_interaction_once,
    select_persona_for_user,
)


def initialize_session(
    body: Any,
    *,
    memory_store: Any,
    memory_enabled: bool,
    logger: logging.Logger,
    module_id: str | None = None,
) -> dict:
    """Initialize or refresh a Chainlit-backed session.

    This is a behavior-preserving extraction from app.main.init_session. Keep
    route-specific request validation in FastAPI; this function owns session
    memory mutation and response shaping.
    """
    if not memory_enabled:
        return {"status": "ok"}

    sid = body.sessionId
    logger.info("Initializing session %s", sid)
    now = time.time()
    mem = memory_store.get(sid)

    character = body.character
    scene = body.scene
    initial_card = body.initialCard
    persona_id = body.personaId

    if not persona_id and mem:
        persona_meta = mem.get("persona") if isinstance(mem.get("persona"), dict) else {}
        persona_id = persona_meta.get("name") or extract_persona_name_from_text(mem.get("character"))
        if persona_id:
            logger.info("Recovered personaId '%s' from existing memory for session %s", persona_id, sid)

    selected_persona = None
    fields: dict[str, Any] | None = None

    if persona_id:
        try:
            selected_persona = find_persona(name=persona_id) or find_persona(persona_id=persona_id)
            if not selected_persona:
                raise ValueError(f"Unknown persona {persona_id}")

            fields = build_persona_session_fields(selected_persona)
            if fields is not None:
                character = character or fields["character"]
                scene = scene or fields["scene"]
                initial_card = initial_card or fields["initial_card"]
        except Exception as exc:
            logger.error("Failed to load persona %s: %s", persona_id, exc)
    elif not mem and not character:
        try:
            from app.services.storage_service import storage_service

            user_info = body.userInfo if isinstance(body.userInfo, dict) else {}
            user_id = user_info.get("identifier")
            selected_persona = select_persona_for_user(
                user_id,
                memory_store,
                load_counts=storage_service.count_personas_for_user,
            )
            fields = build_persona_session_fields(selected_persona)
            if fields is not None:
                character = fields["character"]
                scene = scene or fields["scene"]
                initial_card = initial_card or fields["initial_card"]
        except Exception as exc:
            logger.warning("Failed weighted persona selection for session %s: %s", sid, exc)

    if selected_persona is None and character:
        recovered_persona_name = extract_persona_name_from_text(character)
        if recovered_persona_name:
            selected_persona = find_persona(name=recovered_persona_name)
            if selected_persona:
                fields = build_persona_session_fields(selected_persona)

    if not mem:
        persona_payload = fields["persona"] if selected_persona and fields is not None else None
        mem = {
            "history": [],
            "full_history": [],
            "character": character,
            "scene": scene,
            "persona": persona_payload,
            "module_id": module_id,
            "user_info": body.userInfo,
            "updated": now,
            "session_started": now,
        }
        if selected_persona:
            user_info = body.userInfo if isinstance(body.userInfo, dict) else {}
            record_persona_interaction_once(user_info.get("identifier"), sid, selected_persona, memory_store)

        if character:
            card_content = initial_card or scenario_card_from_character(character)
            history = mem.get("history")
            if not isinstance(history, list):
                history = []
                mem["history"] = history
            full_history = mem.get("full_history")
            if not isinstance(full_history, list):
                full_history = []
                mem["full_history"] = full_history
            history.append({"role": ROLE_SYSTEM, "content": card_content})
            full_history.append({"role": ROLE_SYSTEM, "content": card_content, "time": now})

        memory_store[sid] = mem
    else:
        if character and not mem.get("character"):
            mem["character"] = character
        if scene and not mem.get("scene"):
            mem["scene"] = scene
        if selected_persona and not mem.get("persona"):
            if fields is not None:
                mem["persona"] = fields["persona"]
        if body.userInfo and not mem.get("user_info"):
            mem["user_info"] = body.userInfo
        if module_id and not mem.get("module_id"):
            mem["module_id"] = module_id

        if not mem.get("history") and character:
            if not mem.get("full_history"):
                card_content = initial_card or scenario_card_from_character(character)
                history = mem.get("history")
                if not isinstance(history, list):
                    history = []
                    mem["history"] = history
                full_history = mem.get("full_history")
                if not isinstance(full_history, list):
                    full_history = []
                    mem["full_history"] = full_history
                history.append({"role": ROLE_SYSTEM, "content": card_content})
                full_history.append({"role": ROLE_SYSTEM, "content": card_content, "time": now})

        mem.setdefault("full_history", [])
        mem.setdefault("session_started", now)
        mem["updated"] = now
        memory_store[sid] = mem

    logger.info("Session initialized: %s", sid)

    already_active = _track_connection(body, sid, mem, memory_store, logger)
    return _session_response(body, sid, mem, already_active, initial_card, module_id)


def deregister_session_connection(
    body: Any,
    *,
    memory_store: Any,
    memory_enabled: bool,
    logger: logging.Logger,
) -> dict:
    if not memory_enabled:
        return {"status": "ok"}

    sid = body.sessionId
    mem = memory_store.get(sid)
    if mem:
        active = mem.get("active_connections", [])
        if body.connectionId in active:
            active.remove(body.connectionId)
            mem["active_connections"] = active
            mem["updated"] = time.time()
            memory_store[sid] = mem
            logger.info("Connection deregistered: %s for session %s", body.connectionId, sid)
    return {"status": "ok"}


def scenario_card_from_character(character: str) -> str:
    persona_name = "Person"
    for line in character.splitlines():
        if "Specific Persona:" in line:
            persona_name = line.split("Specific Persona:")[1].strip()
            break
    return f"Person: {persona_name}\n(Scenario initialized)"


def _track_connection(body: Any, sid: str, mem: dict, memory_store: Any, logger: logging.Logger) -> bool:
    active_connections = mem.get("active_connections", [])
    already_active = False

    if body.force:
        logger.info("Force flag detected for session %s. Clearing active connections: %s", sid, active_connections)
        active_connections = []
        mem["active_connections"] = active_connections

    if body.connectionId:
        logger.debug("Checking connectionId: %s for session %s. Existing: %s", body.connectionId, sid, active_connections)
        if body.connectionId not in active_connections:
            if active_connections:
                already_active = True
                logger.info(
                    "Session %s is already active with connections: %s. Blocking new connection: %s",
                    sid,
                    active_connections,
                    body.connectionId,
                )

            active_connections.append(body.connectionId)
            mem["active_connections"] = active_connections
            memory_store[sid] = mem
        else:
            if active_connections and active_connections[0] != body.connectionId:
                already_active = True
            logger.debug(
                "connectionId %s already registered for session %s. alreadyActive=%s",
                body.connectionId,
                sid,
                already_active,
            )

    return already_active


def _session_response(
    _body: Any,
    sid: str,
    mem: dict,
    already_active: bool,
    initial_card: str | None,
    module_id: str | None,
) -> dict:
    persona_data = mem.get("persona")
    persona = persona_data if isinstance(persona_data, dict) else {}
    return {
        "status": "ok",
        "moduleId": mem.get("module_id") or module_id,
        "sessionId": sid,
        "alreadyActive": already_active,
        "character": mem.get("character"),
        "scene": mem.get("scene"),
        "persona": mem.get("persona"),
        "personaId": persona.get("id"),
        "personaName": persona.get("name"),
        "initialCard": next(
            (
                m["content"]
                for m in mem["history"]
                if (m.get("role") or ROLE_ASSISTANT).lower().strip() in {ROLE_SYSTEM, ROLE_ASSISTANT}
                and is_scenario_card(m.get("content"))
            ),
            initial_card,
        ),
    }
