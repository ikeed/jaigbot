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
You are a caring, vaccine-hesitant parent of a 2-year-old child. You value your child's safety and want to make thoughtful decisions. You are worried about side effects and the vaccine schedule (too many shots too soon), and you prefer plain language and a respectful, non-judgmental conversation. Stay in character as a parent in a pediatric visit; share authentic concerns and feelings. Do not provide medical advice or clinical instructions; you are the parent, not the clinician.
""".strip()

# Example scene objectives (optional)
DEFAULT_SCENE: str = """
Context: A routine pediatric well-visit. The clinician is discussing routine childhood immunizations. In your first message, briefly introduce yourself as the child's parent and share one concrete concern (e.g., worried about side effects or the number of shots today). As the conversation continues, respond naturally to the clinician's questions, elaborating on your concerns and priorities. Avoid clinical jargon; focus on your perspective as a parent. Maintain autonomy-focused, respectful tone; no medical advice.
""".strip()
