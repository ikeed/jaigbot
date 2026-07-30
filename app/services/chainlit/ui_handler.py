import logging
from typing import Any, Dict

import chainlit as cl

from app.chat_roles import (
    ROLE_ASSISTANT,
    ROLE_COACH,
    ROLE_SYSTEM,
    ROLE_USER,
    get_ui_attributes,
)
from app.constants import (
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
from app.message_catalog import message
from app.services.coaching_display import (
    coaching_message_parts,
    coaching_summary_text as build_coaching_summary_text,
)

logger = logging.getLogger(__name__)

STEP_LABELS = {
    STEP_ANNOUNCE,
    STEP_INQUIRE,
    STEP_MIRROR,
    STEP_SECURE,
    STEP_ANNOUNCE_INQUIRE,
    STEP_MIRROR_INQUIRE,
    STEP_MIRROR_SECURE,
    STEP_SECURE_INQUIRE,
    STEP_MIRROR_SECURE_INQUIRE,
}


class UIHandler:
    """Handles all formatting and sending of messages to the Chainlit frontend."""

    @staticmethod
    def _format_parts(title: str, parts: list[str]) -> str:
        clean_parts = [UIHandler._normalize_part(p) for p in parts if p and p != title]
        lines: list[str] = []
        for part in clean_parts:
            if not part:
                continue
            if "\n" in part:
                if lines:
                    lines.append("")
                lines.extend(part.splitlines())
            elif part.endswith(":"):
                lines.append(part)
            else:
                lines.append(f"- {part}")
        body = "\n".join(lines)
        return f"**{title}**\n\n{body}" if body else f"**{title}**"

    @staticmethod
    def _normalize_part(part: str) -> str:
        text = (part or "").strip()
        if ":" in text:
            step = text.split(":", 1)[1].strip()
        else:
            step = ""
        if step in STEP_LABELS:
            return message("coaching.step_group_header", step=step) if step else ""
        return text

    @staticmethod
    def format_coach_message(text: str) -> str:
        txt = (text or "").strip()
        if not txt:
            return ""
        if " | " in txt:
            phase_prefix = message("coaching.phase_prefix").lower()
            parts = [
                p.strip()
                for p in txt.split(" | ")
                if p.strip() and not p.strip().lower().startswith(phase_prefix)
            ]
        else:
            parts = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        if not parts:
            return txt
        scenario_complete = message("coaching.scenario_complete")
        title = (
            scenario_complete
            if any(scenario_complete in p for p in parts)
            else message("coaching.section_title")
        )
        return UIHandler._format_parts(title, parts)

    @staticmethod
    def format_coaching_message(coaching: dict[str, Any]) -> str:
        parts = coaching_message_parts(coaching)
        if not parts:
            return ""
        return UIHandler._format_parts(message("coaching.section_title"), parts)

    @staticmethod
    def coaching_summary_text(coaching: dict[str, Any]) -> str:
        return build_coaching_summary_text(coaching)

    @staticmethod
    def render_scenario_card_html(card_text: str) -> str:
        """Render a scenario briefing with consistent HTML styling."""
        lines: list[str] = [
            '<div class="aims-scenario-briefing">',
            f'<div class="aims-scenario-title">{message("chainlit.scenario_briefing")}</div>',
        ]
        for line in (card_text or "").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if ": " in stripped:
                label, value = stripped.split(": ", 1)
                lines.append(
                    '<div class="aims-scenario-line">'
                    f'<span class="aims-scenario-label">{label}:</span> {value}'
                    '</div>'
                )
            else:
                lines.append(f'<div class="aims-scenario-note">{stripped}</div>')
        lines.append("</div>")
        return "".join(lines)

    async def present_scenario_card(self, card: str):
        await cl.Message(
            content=self.render_scenario_card_html(card), 
            **get_ui_attributes(ROLE_SYSTEM)
        ).send()

    @staticmethod
    async def show_error(message: str):
        await cl.Message(message, **get_ui_attributes(ROLE_SYSTEM)).send()

    @staticmethod
    async def send_window_message(payload: Dict[str, Any]):
        await cl.send_window_message(payload)

    @staticmethod
    async def send_user_message_update(message: cl.Message):
        attrs = get_ui_attributes(ROLE_USER)
        message.author = attrs["author"]
        message.type = attrs["type"]
        await message.update()

    @staticmethod
    async def send_assistant_reply(content: str, author_name: str | None = None):
        attrs = get_ui_attributes(ROLE_ASSISTANT)
        await cl.Message(
            content,
            author=(author_name or attrs["author"]),
            type=attrs["type"],
        ).send()

    async def send_coach_message(self, content: str):
        await cl.Message(
            content=self.format_coach_message(content), 
            **get_ui_attributes(ROLE_COACH)
        ).send()

    async def send_coaching_message(self, coaching: dict[str, Any]):
        content = self.format_coaching_message(coaching)
        if not content:
            return
        await cl.Message(
            content=content,
            **get_ui_attributes(ROLE_COACH),
        ).send()
