# AIMS protocol mapping (reference)

This directory contains the AIMS communication protocol as implemented in AIMSBot.

## Files

- **classification-scoring-rules.md** — *Canonical reference* for all classification, scoring,
  deterministic post-processing, phase-state, and endgame rules as currently implemented.
  **Start here if you want to understand how the system works.**

- **AIMS_Approach_Summary.md** — Faithful summary of the original academic paper
  (Parrish-Sprowl et al., 2023).  Describes the theoretical AIMS framework; does not describe
  implementation details.

- **aims_mapping.json** — Operational mapping used by the deterministic fallback engine
  (`app/aims_engine.py`).  The LLM classifier (`app/services/classifier_service.py`) is the
  primary path; this file is consulted on LLM timeout or failure.

- **implementation-plan.md** — Historical implementation notes (may be outdated).

- Reference source: `../../fpubh-11-1120326.pdf` (Frontiers in Public Health article)

## AIMS Steps

The system recognises six step values:

| Step | Description |
|------|-------------|
| `Announce` | First (and only) introduction/recommendation of vaccines |
| `Inquire` | Open question to surface concerns or hesitancy |
| `Mirror` | Reflect the person's concern so they "feel felt" |
| `Mirror+Inquire` | Compound: reflection + open question in one turn |
| `Mirror+Secure` | Compound: reflection + autonomy-supportive education in one turn |
| `Secure` | Affirm autonomy, offer one tailored fact, provide safety-net |

For full scoring rubrics, dependency rules, deterministic guards, and endgame logic see
**classification-scoring-rules.md**.
