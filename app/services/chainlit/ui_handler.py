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

logger = logging.getLogger(__name__)

class UIHandler:
    """Handles all formatting and sending of messages to the Chainlit frontend."""

    @staticmethod
    def _startup_artifact_title(artifact: Dict[str, Any] | None, fallback: str = "Session Briefing") -> str:
        if isinstance(artifact, dict):
            title = artifact.get("title")
            if isinstance(title, str) and title.strip():
                return title.strip()
        return fallback

    @staticmethod
    def format_coach_message(text: str) -> str:
        txt = (text or "").strip()
        if not txt:
            return ""
        if " | " in txt:
            parts = [
                p.strip()
                for p in txt.split(" | ")
                if p.strip() and not p.strip().lower().startswith("conversation phase:")
            ]
        else:
            parts = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        if not parts:
            return txt
        title = "Scenario complete" if any("Scenario complete" in p for p in parts) else "Coaching"
        clean_parts = [p for p in parts if p != title]
        bullets = "\n".join(f"- {p}" for p in clean_parts)
        return f"**{title}**\n\n{bullets}" if bullets else f"**{title}**"

    @staticmethod
    def render_startup_artifact_html(artifact: Dict[str, Any] | None = None, *, card_text: str | None = None) -> str:
        """Render a startup artifact with consistent HTML styling."""
        title = UIHandler._startup_artifact_title(artifact)
        text = card_text
        if text is None and isinstance(artifact, dict):
            artifact_content = artifact.get("content")
            text = artifact_content if isinstance(artifact_content, str) else ""

        lines: list[str] = [
            '<div class="aims-scenario-briefing">',
            f'<div class="aims-scenario-title">{title}</div>',
        ]
        for line in (text or "").splitlines():
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

    @staticmethod
    def render_scenario_card_html(card_text: str) -> str:
        return UIHandler.render_startup_artifact_html(card_text=card_text)

    async def present_scenario_card(self, card: str):
        await cl.Message(
            content=self.render_scenario_card_html(card), 
            **get_ui_attributes(ROLE_SYSTEM)
        ).send()

    async def present_startup_artifact(self, artifact: Dict[str, Any]):
        await cl.Message(
            content=self.render_startup_artifact_html(artifact),
            **get_ui_attributes(ROLE_SYSTEM)
        ).send()

    @staticmethod
    async def show_error(message: str):
        await cl.Message(message, **get_ui_attributes(ROLE_SYSTEM)).send()

    @staticmethod
    async def send_window_message(payload: Dict[str, Any]):
        await cl.send_window_message(payload)

    @staticmethod
    async def send_user_message_update(
        message: cl.Message,
        *,
        author_name: str | None = None,
        role_labels: Dict[str, str] | None = None,
    ):
        attrs = get_ui_attributes(ROLE_USER, role_labels=role_labels)
        message.author = attrs["author"]
        if author_name:
            message.author = author_name
        message.type = attrs["type"]
        await message.update()

    @staticmethod
    async def send_assistant_reply(
        content: str,
        author_name: str | None = None,
        role_labels: Dict[str, str] | None = None,
    ):
        attrs = get_ui_attributes(ROLE_ASSISTANT, role_labels=role_labels)
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
