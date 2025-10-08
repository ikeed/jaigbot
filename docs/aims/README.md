# AIMS protocol mapping (reference)

This directory contains a structured mapping of the AIMS communication protocol used in vaccine conversations:
- Announce
- Inquire
- Mirror
- Secure

Files:
- aims_mapping.json — a comprehensive, operational mapping for recognizing and evaluating each AIMS step.
- Reference source: ../../fpubh-11-1120326.pdf (Frontiers in Public Health article)

Intended uses of aims_mapping.json
1. Developer/reference: as a precise spec for implementing AIMS behavior in the bot.
2. Classification: to classify a clinician/user turn into one of the four AIMS steps.
3. Per-turn evaluation: given the last two messages (parent then clinician) and the step, evaluate execution quality.
4. Coaching: generate immediate, constructive hints after each turn.
5. Overall scoring: aggregate per-turn scores at the end of a conversation.

Notes
- This directory is currently documentation/reference; no runtime imports use it yet. Future code can load it from docs/aims/aims_mapping.json or embed its content in code/constants.
- See docs/memory-and-persona.md and docs/plan.md for broader context on conversation flow and upcoming implementation steps.
- Roadmap: see implementation tasks in docs/aims/implementation-plan.md (kept up to date as work progresses).
