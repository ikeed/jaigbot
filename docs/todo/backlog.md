# Backlog (post-MVP)

Status: living list of items to revisit after core AIMS coaching stabilizes.

Priority buckets
- P0: correctness/safety
- P1: robustness/UX
- P2: polish/nice-to-have

Items

P0 — Safety and correctness
- Refine jailbreak/meta detection patterns; add unit tests with adversarial phrasing variants.
- Consider adding a server-side content filter for misinformation tropes (patient should not educate; keep feelings-first). Evaluate false-positives.
- Evaluate adding a stricter schema for patient replies (e.g., forbid URLs) if abuse observed.

P1 — Robustness and UX
- /summary narrative: add optional LLM-generated narrative with strict schema, 1 retry then fallback (omit narrative); tests and examples.
- Chainlit coaching UI: add toggle bound to $AIMS_COACHING_ENABLED; minimal panel to show step + text feedback; summary modal with numeric scores.
- Redis diagnostics endpoint: lightweight /diagnostics memory view that shows per-session metrics count only (no content), to aid debugging.
- Expand logging around fallback paths with a correlation id per LLM call.

P2 — Polish
- Persona mutation at session start based on persona_seed.txt; persist chosen seed per session.
- Configurable patterns lists via env or a small JSON file (reload on SIGHUP) for safety/jailbreak.
- Add docs with sample curated transcripts and “golden path” AIMS interactions.

Notes
- Keep raw logs capped (SAFETY_LOG_CAP) to prevent runaway lines.
- Reassess whether to keep the user-facing safety error string vs. a gentler in-character response once dev stabilizes.
