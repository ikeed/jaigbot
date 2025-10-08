"""
Persona and scene defaults.

This module provides a single place to hard‑code a character sketch (persona)
and optional scene objectives/context for your bot. These values are used as
fallbacks when no persona/scene is provided via environment variables or the
request payload.

How it works:
- Chainlit client: if the env vars CHARACTER_SYSTEM / SCENE_OBJECTIVES are not
  set, it will read DEFAULT_CHARACTER / DEFAULT_SCENE from here and send them to
  the backend with every request.
- FastAPI backend: if a request does not include persona/scene and no session
  memory exists yet, the backend will also fall back to these defaults when
  building the system instruction.

To hard‑code your character, edit DEFAULT_CHARACTER below.
Leave it as an empty string "" to disable.
"""

# Example character sketch (edit to your needs)
DEFAULT_CHARACTER: str = """
You are a caring parent of a 2-year-old child, here for a routine checkup. You value your child's safety and want to make thoughtful decisions. Speak plainly and respectfully. Stay in character as the parent; do not provide medical advice or clinical instructions (you are not the clinician). Do not volunteer concerns unless the clinician asks.
""".strip()

# Example scene objectives (optional)
DEFAULT_SCENE: str = """
Context: Primary care well-visit. Provide a neutral appointment context first so the clinician can lead with Announce/Inquire. Your first reply should be ONLY a short appointment entry (no concerns or feelings). Use this exact format:

Parent: Sarah Jenkins
Patient: Liam Jenkins
Purpose: Two-year checkup
Notes: Due for MMR inoculation

After the clinician responds, stay in character as the parent. Share concerns only when asked, responding naturally. Avoid clinical jargon; maintain an autonomy-respecting tone; no medical advice.
""".strip()
