import logging
import chainlit as cl
from typing import Any, Dict, List, Optional
from app.chat_roles import (
    ROLE_ASSISTANT,
    ROLE_COACH,
    ROLE_SYSTEM,
    ROLE_USER,
    get_ui_attributes,
    is_scenario_card,
)

logger = logging.getLogger(__name__)

class UIHandler:
    """Handles all formatting and sending of messages to the Chainlit frontend."""

    async def replay_history(self, history: List[Dict[str, Any]]):
        """Replay all prior messages to the UI."""
        for item in history or []:
            role = (item.get("role") or ROLE_ASSISTANT).lower().strip()
            content = item.get("content", "")

            # Legacy sessions stored scenario cards as assistant messages.
            if role == ROLE_ASSISTANT and is_scenario_card(content):
                role = ROLE_SYSTEM

            attrs = get_ui_attributes(role)
            author = attrs["author"]
            msg_type = attrs["type"]

            if role == ROLE_SYSTEM and is_scenario_card(content):
                await cl.Message(
                    content=self.render_scenario_card_html(content), 
                    author=author, 
                    type=msg_type
                ).send()
                continue

            if role == ROLE_COACH:
                try:
                    coach_text = self.format_coach_message(content)
                    if coach_text:
                        await cl.Message(content=coach_text, author=author, type=msg_type).send()
                        continue
                except Exception as e:
                    logger.debug(f"Failed to format coach message during replay (non-fatal): {e}")
                    pass

            # Non-coach or fallback
            content_clean = self._strip_export_artifacts(content)
            await cl.Message(content=content_clean, author=author, type=msg_type).send()

    def format_coach_message(self, text: str) -> str:
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

    def render_scenario_card_html(self, card_text: str) -> str:
        """Render a scenario briefing with consistent HTML styling."""
        lines: list[str] = [
            '<div class="aims-scenario-briefing">',
            '<div class="aims-scenario-title">Scenario Briefing</div>',
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

    async def show_error(self, message: str):
        await cl.Message(message, **get_ui_attributes(ROLE_SYSTEM)).send()

    async def send_window_message(self, payload: Dict[str, Any]):
        await cl.send_window_message(payload)

    async def send_user_message_update(self, message: cl.Message):
        attrs = get_ui_attributes(ROLE_USER)
        message.author = attrs["author"]
        message.type = attrs["type"]
        await message.update()

    async def send_assistant_reply(self, content: str):
        await cl.Message(content, **get_ui_attributes(ROLE_ASSISTANT)).send()

    async def send_coach_message(self, content: str):
        await cl.Message(
            content=self.format_coach_message(content), 
            **get_ui_attributes(ROLE_COACH)
        ).send()

    def _strip_export_artifacts(self, text: str) -> str:
        try:
            lines = [ln for ln in (text or "").splitlines() if ln.strip() and not ln.strip().lower().startswith("avatar for ")]
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Error stripping artifacts from text: {e}")
            return text
