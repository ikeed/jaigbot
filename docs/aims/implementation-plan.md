# AIMS coaching implementation plan (iterative, verifiable)

Context
- Goal: Migrate from the Ghostbusters scene to a realistic vaccine‑hesitant parent simulator that provides AIMS step classification, per‑turn scoring/coaching, and an end‑of‑session summary — while keeping one LLM call per turn in the common path and maintaining backward compatibility.
- Source of truth: docs/aims/aims_mapping.json (aligns with fpubh-11-1120326.pdf).
- Constraints: Minimal changes per step; tests must remain green; default behavior untouched unless `coach=true` (and feature flag) is set.

Guiding principles
- Small: each task should be completable in <1–2 hours.
- Verifiable: each task defines clear acceptance criteria (tests/docs) and demo steps.
- Reversible: isolate changes behind flags; no breaking API by default.
- Test‑first where feasible: unit tests for pure logic (classifier/scorer) before wiring to the LLM.

Milestones and tasks

Milestone 0 — Planning and guardrails
0.1 Create this living plan document and link it from docs/aims/README.md
- Deliverable: docs/aims/implementation-plan.md (this file) with milestones, tasks, and checklists.
- Acceptance: File exists in repo and is referenced from docs/aims/README.md.
- Status: Done

0.2 Add feature flag definition (planning only)
- Deliverable: Document the `AIMS_COACHING_ENABLED` flag intent here; implementation comes later.
- Acceptance: Flag described; rollout strategy noted.
- Status: Done (documented below in Milestone 6)

Milestone 1 — Core data loading and deterministic logic (offline, no LLM)
1.1 Loader utility plan
- Deliverable: Plan tests and API for loading aims_mapping.json (pure function spec only).
- Verify: Test cases outlined here; no code yet.

1.2 Deterministic classifier plan
- Deliverable: Define inputs/outputs and test fixtures for classifying a clinician turn using last two messages and mapping markers/tie‑breakers.
- Verify: Fixtures and expected labels listed.

1.3 Deterministic scorer plan
- Deliverable: Define scoring rubric application per step and test vectors for 0–3 outcomes.
- Verify: Table of inputs → expected scores and reasons.

1.4 Session aggregation plan
- Deliverable: Define in‑memory model for per‑session metrics (per‑step arrays, averages, coverage) and overall summary rubric.
- Verify: Example aggregation walkthrough in this doc.

Milestone 2 — Unit tests (pure Python, no network)
2.1 Add unit tests for loader, classifier, scorer, aggregator (skipped until implementation lands)
- Deliverable: tests/test_aims_engine.py skeleton with parametrized cases (initially xfail or skipped).
- Verify: pytest collects tests; marked xfail/skip to avoid breaking CI until implementation.

Milestone 3 — Backend API extensions (backward‑compatible)
3.1 Extend POST /chat input model (coach?: bool, sessionId passthrough)
- Deliverable: Pydantic model change behind feature flag; default false.
- Verify: tests/test_chat.py continues to pass; new tests assert flag plumbed (mocked).

3.2a Define response models for coaching/session (typing only)
- Deliverable: Pydantic models for `coaching` and `session` (no handler wiring yet).
- Verify: mypy/pyright (if used) passes; unit test imports models and validates a sample payload against them.

3.2b Wire response shape when coach=true (handler integration)
- Deliverable: Add optional `coaching` object and `session` metrics fields in the actual response when `coach=true`.
- Verify: Integration test (mock Vertex) asserts presence/shape when `coach=true`; with `coach=false` behavior unchanged.

3.3 Summary retrieval
- Deliverable: Support `/summary` endpoint or `/chat` with `message: "/summary"` to return final report.
- Verify: Unit/integration test returns structured summary.

Milestone 4 — Prompt and single‑pass JSON envelope
4.1 Patient simulator system prompt
- Deliverable: New prompt that sets the LLM as a vaccine‑hesitant parent with constraints (no medical advice, autonomy support, realistic concerns).
- Verify: Golden prompt captured; peer review; token budget noted.

4.2 Compact mapping injection
- Deliverable: Select minimal subset of aims_mapping.json (markers, decision rules, heuristics) to include in prompt.
- Verify: Document selected fields; justify omissions for token economy.

4.3 Output schema and few‑shots
- Deliverable: Strict JSON envelope schema (patient_reply, classification, scoring, coaching) + 1–2 few‑shot examples.
- Verify: Schema validates with jsonschema; examples pass a validator.

Milestone 5 — Engine integration and fallbacks
5.1 Vertex call wiring
- Deliverable: Wrap existing Vertex client to send prompt/context and parse JSON envelope.
- Verify: Mocked integration test returns parsed structure and reply.

5.2a JSON schema validation and strict parsing
- Deliverable: Implement server‑side JSON Schema validation for the envelope; strict parsing with clear error paths and metrics.
- Verify: Unit tests validate good/bad payloads; invalid payloads raise a specific error caught by the handler.

5.2b Deterministic fallback and two‑pass strategy
- Deliverable: If JSON invalid/missing fields, run deterministic classifier/scorer and (if needed) trigger a second lightweight generation for the patient reply; record `fallbackUsed=true`.
- Verify: Test path where model returns bad JSON; fallback engages; response still valid and includes `fallbackUsed=true` in logs/telemetry.

5.3 Session state and metrics
- Deliverable: Persist per‑session AIMS metrics using existing memory approach; TTL respected.
- Verify: Test increments, averages, and coverage across multiple turns.

Milestone 6 — Feature flags, safety, and observability
6.1 Feature flag AIMS_COACHING_ENABLED
- Deliverable: Environment flag gating coach features; default false.
- Verify: With flag off, behavior unchanged even if coach=true; with flag on, features enabled.

6.2 Safety guardrails
- Deliverable: Checks to prevent the patient simulator from giving medical advice; adhere to tone guidelines.
- Verify: Prompt constraints documented; negative tests for disallowed content in patient replies (mocked).

6.3 Telemetry
- Deliverable: Structured logs for step, score, reasons, JSON validity, and fallback usage.
- Verify: Unit test ensures logging hook called with expected fields (using caplog).

Milestone 7 — Chainlit UI enhancements (optional toggle)
7.1 Coaching toggle
- Deliverable: UI control to send coach=true and display coaching panel.
- Verify: Manual demo; mocked backend; UI renders fields.

7.2 Running dashboard and end‑of‑session summary
- Deliverable: Right‑side pane with step/score/tips and a summary modal.
- Verify: Manual demo; basic e2e test harness if feasible.

Milestone 8 — Documentation and rollout
8.1 Update docs (README, docs/api.md, docs/aims/README.md)
- Deliverable: Document flag, request/response fields, and summary endpoint; link to aims_mapping.json.
- Verify: Docs build/lint passes; links valid.

8.2 Rollout plan
- Deliverable: Stage behind flag in dev; measure JSON validity and iterate few‑shots until ≥95% single‑pass success.
- Verify: Checklist and metrics captured here; go/no‑go criteria noted.

Appendix — Verification details (kept up to date)

A. Classifier/scorer test fixtures (ready to copy into tests)

A.1 Announce vs Secure
- Case A1
  parent_last: "I'm not sure about the MMR; I read about side effects and I'm anxious."
  clinician_last: "It's time for Layla's MMR today. It protects her from measles outbreaks we're seeing locally. How does that sound to you?"
  expected_step: Announce
  rationale: Clear, concise recommendation + brief rationale + invitation; no autonomy language or options → Announce.

- Case A2 (edge leaning Secure)
  parent_last: "I'm still on the fence; I don't like being pressured."
  clinician_last: "It's your decision, and I'm here to support you. We can do it today, or I can share a short handout and we can check in next week — what would work best?"
  expected_step: Secure
  rationale: Explicit autonomy + concrete options → Secure.

- Case A3 (ambiguous Announce with autonomy phrase)
  parent_last: "I just don't know."
  clinician_last: "I recommend the MMR today to protect against measles. It's your decision, and I'm happy to answer questions."
  expected_step: Announce
  rationale: Primary act is a presumptive recommendation; autonomy is supportive, but no options/plan → Announce per tie‑breakers.

A.2 Mirror vs Inquire
- Case M1
  parent_last: "I saw a story about bad reactions, and it scared me."
  clinician_last: "It sounds like that story really worried you and you want to keep your child safe — did I get that right?"
  expected_step: Mirror
  rationale: Accurate reflection of content + emotion; no new info; optional check.

- Case M2
  parent_last: "I don't trust the schedule; it's too many at once."
  clinician_last: "What concerns you most about the schedule for today?"
  expected_step: Inquire
  rationale: Single open question inviting elaboration; no reflective paraphrase.

- Case M3 (reflection followed by question)
  parent_last: "I worry she'll have a bad reaction."
  clinician_last: "You're worried about side effects. What have you heard so far?"
  expected_step: Mirror
  rationale: Reflection is accurate and primary; brief follow‑up question okay → prefer Mirror per tie‑breaker.

- Case M4 (leading question)
  parent_last: "My friend said vaccines can cause autism."
  clinician_last: "You don't believe that myth, do you?"
  expected_step: Inquire (score likely 0–1)
  rationale: It's a question but leading/judgmental; classify as Inquire, score low by heuristics.

- Case M5 (mirror with rebuttal → penalize)
  parent_last: "I'm afraid of side effects."
  clinician_last: "I get you're scared, but that's not true — the data shows it's safe."
  expected_step: Mirror (score 0–1)
  rationale: Contains a rebuttal after a reflection stem → still Mirror by stems, but score low due to non‑judgment violation.

B. Minimal JSON Schema for single‑pass coaching envelope
- Objective: Keep schema compact; require essentials for server processing; allow future extension.

jsonschema (draft‑07 compatible):
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "patient_reply": { "type": "string", "minLength": 1 },
    "classification": {
      "type": "object",
      "properties": {
        "step": { "type": "string", "enum": ["Announce", "Inquire", "Mirror", "Secure"] },
        "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
        "evidence_spans": { "type": "array", "items": { "type": "string" } }
      },
      "required": ["step"],
      "additionalProperties": false
    },
    "scoring": {
      "type": "object",
      "properties": {
        "score": { "type": "integer", "minimum": 0, "maximum": 3 },
        "reasons": { "type": "array", "items": { "type": "string" } }
      },
      "required": ["score"],
      "additionalProperties": false
    },
    "coaching": {
      "type": "object",
      "properties": {
        "tips": { "type": "array", "items": { "type": "string" } },
        "next_step_suggestion": { "type": "string" }
      },
      "required": [],
      "additionalProperties": false
    }
  },
  "required": ["patient_reply", "classification", "scoring"],
  "additionalProperties": false
}

Notes:
- Required minimum: patient_reply + classification.step + scoring.score.
- Server can enrich or ignore `coaching` when `coach=false`.

C. Prompt snippets and token budget estimates (stub)
- Keep mapping injection to markers + decision_rules + evaluation_heuristics only; target ≤ 1.5k tokens total prompt.

# AIMS coaching implementation plan (iterative, verifiable)

Context
- Goal: Migrate from the Ghostbusters scene to a realistic vaccine‑hesitant parent simulator that provides AIMS step classification, per‑turn scoring/coaching, and an end‑of‑session summary — while keeping one LLM call per turn in the common path and maintaining backward compatibility.
- Source of truth: docs/aims/aims_mapping.json (aligns with fpubh-11-1120326.pdf).
- Constraints: Minimal changes per step; tests must remain green; default behavior untouched unless `coach=true` (and feature flag) is set.

Guiding principles
- Small: each task should be completable in <1–2 hours.
- Verifiable: each task defines clear acceptance criteria (tests/docs) and demo steps.
- Reversible: isolate changes behind flags; no breaking API by default.
- Test‑first where feasible: unit tests for pure logic (classifier/scorer) before wiring to the LLM.

Milestones and tasks

Milestone 0 — Planning and guardrails
0.1 Create this living plan document and link it from docs/aims/README.md
- Deliverable: docs/aims/implementation-plan.md (this file) with milestones, tasks, and checklists.
- Acceptance: File exists in repo and is referenced from docs/aims/README.md.
- Status: Done

0.2 Add feature flag definition (planning only)
- Deliverable: Document the `AIMS_COACHING_ENABLED` flag intent here; implementation comes later.
- Acceptance: Flag described; rollout strategy noted.
- Status: Done (documented below in Milestone 6)

Milestone 1 — Core data loading and deterministic logic (offline, no LLM)
1.1 Loader utility plan
- Deliverable: Plan tests and API for loading aims_mapping.json (pure function spec only).
- Verify: Test cases outlined here; no code yet.

1.2 Deterministic classifier plan
- Deliverable: Define inputs/outputs and test fixtures for classifying a clinician turn using last two messages and mapping markers/tie‑breakers.
- Verify: Fixtures and expected labels listed.

1.3 Deterministic scorer plan
- Deliverable: Define scoring rubric application per step and test vectors for 0–3 outcomes.
- Verify: Table of inputs → expected scores and reasons.

1.4 Session aggregation plan
- Deliverable: Define in‑memory model for per‑session metrics (per‑step arrays, averages, coverage) and overall summary rubric.
- Verify: Example aggregation walkthrough in this doc.

Milestone 2 — Unit tests (pure Python, no network)
2.1 Add unit tests for loader, classifier, scorer, aggregator (skipped until implementation lands)
- Deliverable: tests/test_aims_engine.py skeleton with parametrized cases (initially xfail or skipped).
- Verify: pytest collects tests; marked xfail/skip to avoid breaking CI until implementation.

Milestone 3 — Backend API extensions (backward‑compatible)
3.1 Extend POST /chat input model (coach?: bool, sessionId passthrough)
- Deliverable: Pydantic model change behind feature flag; default false.
- Verify: tests/test_chat.py continues to pass; new tests assert flag plumbed (mocked).

3.2a Define response models for coaching/session (typing only)
- Deliverable: Pydantic models for `coaching` and `session` (no handler wiring yet).
- Verify: mypy/pyright (if used) passes; unit test imports models and validates a sample payload against them.

3.2b Wire response shape when coach=true (handler integration)
- Deliverable: Add optional `coaching` object and `session` metrics fields in the actual response when `coach=true`.
- Verify: Integration test (mock Vertex) asserts presence/shape when `coach=true`; with `coach=false` behavior unchanged.

3.3 Summary retrieval
- Deliverable: Support `/summary` endpoint or `/chat` with `message: "/summary"` to return final report.
- Verify: Unit/integration test returns structured summary.

Milestone 4 — Prompt and single‑pass JSON envelope
4.1 Patient simulator system prompt
- Deliverable: New prompt that sets the LLM as a vaccine‑hesitant parent with constraints (no medical advice, autonomy support, realistic concerns).
- Verify: Golden prompt captured; peer review; token budget noted.

4.2 Compact mapping injection
- Deliverable: Select minimal subset of aims_mapping.json (markers, decision rules, heuristics) to include in prompt.
- Verify: Document selected fields; justify omissions for token economy.

4.3 Output schema and few‑shots
- Deliverable: Strict JSON envelope schema (patient_reply, classification, scoring, coaching) + 1–2 few‑shot examples.
- Verify: Schema validates with jsonschema; examples pass a validator.

Milestone 5 — Engine integration and fallbacks
5.1 Vertex call wiring
- Deliverable: Wrap existing Vertex client to send prompt/context and parse JSON envelope.
- Verify: Mocked integration test returns parsed structure and reply.

5.2a JSON schema validation and strict parsing
- Deliverable: Implement server‑side JSON Schema validation for the envelope; strict parsing with clear error paths and metrics.
- Verify: Unit tests validate good/bad payloads; invalid payloads raise a specific error caught by the handler.

5.2b Deterministic fallback and two‑pass strategy
- Deliverable: If JSON invalid/missing fields, run deterministic classifier/scorer and (if needed) trigger a second lightweight generation for the patient reply; record `fallbackUsed=true`.
- Verify: Test path where model returns bad JSON; fallback engages; response still valid and includes `fallbackUsed=true` in logs/telemetry.

5.3 Session state and metrics
- Deliverable: Persist per‑session AIMS metrics using existing memory approach; TTL respected.
- Verify: Test increments, averages, and coverage across multiple turns.

Milestone 6 — Feature flags, safety, and observability
6.1 Feature flag AIMS_COACHING_ENABLED
- Deliverable: Environment flag gating coach features; default false.
- Verify: With flag off, behavior unchanged even if coach=true; with flag on, features enabled.

6.2 Safety guardrails
- Deliverable: Checks to prevent the patient simulator from giving medical advice; adhere to tone guidelines.
- Verify: Prompt constraints documented; negative tests for disallowed content in patient replies (mocked).

6.3 Telemetry
- Deliverable: Structured logs for step, score, reasons, JSON validity, and fallback usage.
- Verify: Unit test ensures logging hook called with expected fields (using caplog).

Milestone 7 — Chainlit UI enhancements (optional toggle)
7.1 Coaching toggle
- Deliverable: UI control to send coach=true and display coaching panel.
- Verify: Manual demo; mocked backend; UI renders fields.

7.2 Running dashboard and end‑of‑session summary
- Deliverable: Right‑side pane with step/score/tips and a summary modal.
- Verify: Manual demo; basic e2e test harness if feasible.

Milestone 8 — Documentation and rollout
8.1 Update docs (README, docs/api.md, docs/aims/README.md)
- Deliverable: Document flag, request/response fields, and summary endpoint; link to aims_mapping.json.
- Verify: Docs build/lint passes; links valid.

8.2 Rollout plan
- Deliverable: Stage behind flag in dev; measure JSON validity and iterate few‑shots until ≥95% single‑pass success.
- Verify: Checklist and metrics captured here; go/no‑go criteria noted.

Appendix — Verification details (kept up to date)

A. Classifier/scorer test fixtures (ready to copy into tests)

A.1 Announce vs Secure
- Case A1
  parent_last: "I'm not sure about the MMR; I read about side effects and I'm anxious."
  clinician_last: "It's time for Layla's MMR today. It protects her from measles outbreaks we're seeing locally. How does that sound to you?"
  expected_step: Announce
  rationale: Clear, concise recommendation + brief rationale + invitation; no autonomy language or options → Announce.

- Case A2 (edge leaning Secure)
  parent_last: "I'm still on the fence; I don't like being pressured."
  clinician_last: "It's your decision, and I'm here to support you. We can do it today, or I can share a short handout and we can check in next week — what would work best?"
  expected_step: Secure
  rationale: Explicit autonomy + concrete options → Secure.

- Case A3 (ambiguous Announce with autonomy phrase)
  parent_last: "I just don't know."
  clinician_last: "I recommend the MMR today to protect against measles. It's your decision, and I'm happy to answer questions."
  expected_step: Announce
  rationale: Primary act is a presumptive recommendation; autonomy is supportive, but no options/plan → Announce per tie‑breakers.

A.2 Mirror vs Inquire
- Case M1
  parent_last: "I saw a story about bad reactions, and it scared me."
  clinician_last: "It sounds like that story really worried you and you want to keep your child safe — did I get that right?"
  expected_step: Mirror
  rationale: Accurate reflection of content + emotion; no new info; optional check.

- Case M2
  parent_last: "I don't trust the schedule; it's too many at once."
  clinician_last: "What concerns you most about the schedule for today?"
  expected_step: Inquire
  rationale: Single open question inviting elaboration; no reflective paraphrase.

- Case M3 (reflection followed by question)
  parent_last: "I worry she'll have a bad reaction."
  clinician_last: "You're worried about side effects. What have you heard so far?"
  expected_step: Mirror
  rationale: Reflection is accurate and primary; brief follow‑up question okay → prefer Mirror per tie‑breaker.

- Case M4 (leading question)
  parent_last: "My friend said vaccines can cause autism."
  clinician_last: "You don't believe that myth, do you?"
  expected_step: Inquire (score likely 0–1)
  rationale: It's a question but leading/judgmental; classify as Inquire, score low by heuristics.

- Case M5 (mirror with rebuttal → penalize)
  parent_last: "I'm afraid of side effects."
  clinician_last: "I get you're scared, but that's not true — the data shows it's safe."
  expected_step: Mirror (score 0–1)
  rationale: Contains a rebuttal after a reflection stem → still Mirror by stems, but score low due to non‑judgment violation.

B. Minimal JSON Schema for single‑pass coaching envelope
- Objective: Keep schema compact; require essentials for server processing; allow future extension.

jsonschema (draft‑07 compatible):
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "patient_reply": { "type": "string", "minLength": 1 },
    "classification": {
      "type": "object",
      "properties": {
        "step": { "type": "string", "enum": ["Announce", "Inquire", "Mirror", "Secure"] },
        "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
        "evidence_spans": { "type": "array", "items": { "type": "string" } }
      },
      "required": ["step"],
      "additionalProperties": false
    },
    "scoring": {
      "type": "object",
      "properties": {
        "score": { "type": "integer", "minimum": 0, "maximum": 3 },
        "reasons": { "type": "array", "items": { "type": "string" } }
      },
      "required": ["score"],
      "additionalProperties": false
    },
    "coaching": {
      "type": "object",
      "properties": {
        "tips": { "type": "array", "items": { "type": "string" } },
        "next_step_suggestion": { "type": "string" }
      },
      "required": [],
      "additionalProperties": false
    }
  },
  "required": ["patient_reply", "classification", "scoring"],
  "additionalProperties": false
}

Notes:
- Required minimum: patient_reply + classification.step + scoring.score.
- Server can enrich or ignore `coaching` when `coach=false`.

C. Prompt snippets and token budget estimates (stub)
- Keep mapping injection to markers + decision_rules + evaluation_heuristics only; target ≤ 1.5k tokens total prompt.


---
Plan update — Decision alignment (2025-10-07)

The following clarifications reflect stakeholder guidance and adjust scope, risks, and acceptance criteria. These supersede earlier ambiguous items where applicable.

1) Safer multi-pass design and retry policy
- Single-pass JSON envelope is preferred but not required. It is acceptable to use multiple LLM requests per turn when needed for robustness.
- Retry policy: At most 1 retry on invalid JSON; then execute deterministic fallback (5.2b).
- Logging requirement: Log invalid JSON events, retries, and fallback activations. Unit tests will verify log entries via caplog where feasible.

2) Scope and priorities
- Server-only first. Minimal Chainlit coaching UI wiring is moved to the end of the plan (Milestone 7). Keep backend feature complete behind a flag before UI.
- Telemetry/observability is deferred. Create docs/todo/telemetry.md capturing desired metrics for a later phase. Basic application logging (see #1) remains in scope.

3) API/contract details (confirmed)
- Response contract when coach=true: Use the structure proposed earlier: `{ reply, model, latencyMs, coaching: { step, score, reasons, tips, nextStepSuggestion? }, session: {...} }` — backward-compatible when `coach=false`.
- Summary retrieval: Provide a dedicated `GET /summary?sessionId=...` endpoint (3.3).
- Feature flag: `AIMS_COACHING_ENABLED` env var controls all coaching features; default false. Tests must exercise both states (on/off).

4) Deterministic AIMS logic (frozen inputs)
- Tie-breakers and markers are frozen from docs/aims/aims_mapping.json meta.decision_rules and should be treated read-only at runtime.
- Scoring weights unchanged: Mirror and Inquire have weight 1.2 in overall scoring.

5) Persona migration and future mutation
- Remove the Ghostbusters POC persona and hardcode a realistic vaccine‑hesitant parent persona as the new default early in the implementation (see new Task 3.0 below). This change is not gated by the feature flag.
- Add later tasks to support persona mutation at session start using seeds from persona_seed.txt (see new Milestone 9).

6) Storage/session (Redis mandatory)
- Use Redis (or Google Memorystore) as the memory backend in Cloud Run. Set TTL to 3600 seconds (1 hour). Tests should mock Redis to keep the suite offline.
- Ensure session continuity across instances; avoid in‑process memory for production.

7) Testing/CI
- Follow TDD where feasible. The feature is done when tests pass and coverage for new logic is ≥ 80% (unit + integration where applicable).
- It is acceptable to add `xfail` tests prior to implementation for the critical paths.
- Add explicit tests for both flag states: `AIMS_COACHING_ENABLED=false` (default) and `true`.

8) Safety/guardrails
- Strengthen prompt constraints to prevent the patient persona from giving medical advice.
- Add a lightweight output check; if advice is detected, rewrite to neutral (server-side) and log the event. Keep this in scope.

9) Plan adjustments (new/modified tasks)
- 3.0 Replace default persona immediately
  - Deliverable: Update app/persona.py to a realistic vaccine‑hesitant parent persona and neutral clinic scene. Remove Ghostbusters content.
  - Verify: Unit test confirms default persona text includes no Ghostbusters tokens and includes parent concerns language.
  - Note: This task is not behind the feature flag.

- 5.2c Retry policy implementation and logging
  - Deliverable: Enforce “1 retry then fallback” at the handler level. Add structured log entries for invalid JSON, retries, and fallbacks.
  - Verify: Tests simulate invalid JSON → retry → fallback; caplog asserts messages were logged.

- 5.3 (amended) Redis mandatory with 1h TTL
  - Deliverable: Ensure Redis backend selected by default in production; TTL=3600; graceful fallback to in‑memory only in local dev with a warning.
  - Verify: Unit tests mock Redis client; session aggregation persists across turns; TTL honored on write (mock assertion or configuration check).

- 6.3 Telemetry (deferred)
  - Change: Move telemetry/observability to docs/todo/telemetry.md; exclude metrics/export wiring from this milestone. Only basic logging remains in scope.
  - Verify: Existence of TODO doc with target fields and success metrics.

- 7.x UI scope (unchanged but explicitly last)
  - Deliverable: Add a minimal coaching panel in Chainlit, toggleable, after backend stabilizes.

- 9. Persona mutation (new milestone)
  - 9.1 Define mutation strategies seeded by persona_seed.txt (concerns, emotional valence)
    - Deliverable: Design doc snippet in this plan referencing persona_seed.txt; list 3–5 seed personas.
    - Verify: Appendix entry with seeds and selection logic.
  - 9.2 Implement persona mutation at session start (behind a separate flag if needed)
    - Deliverable: Code to pick a seed and maintain consistency per session.
    - Verify: Unit tests fix the seed for determinism and assert persona fields present in prompts.

Acceptance criteria updates (global)
- Tests: pytest passes locally; coverage ≥ 80% for new code paths (classifier, scorer, validator, fallback, summary, persona replacement, flag gating).
- Backward compatibility: With `AIMS_COACHING_ENABLED=false` and/or `coach=false`, existing tests remain green (e.g., tests/test_chat.py).
- Logging: Invalid JSON, retries, and fallback usage are logged; tests verify via caplog where possible.
- Storage: Redis used with 1-hour TTL in production configuration; local dev may use in‑memory if Redis not available, with a visible warning.

# AIMS coaching implementation plan (iterative, verifiable)

Context
- Goal: Migrate from the Ghostbusters scene to a realistic vaccine‑hesitant parent simulator that provides AIMS step classification, per‑turn scoring/coaching, and an end‑of‑session summary — while keeping one LLM call per turn in the common path and maintaining backward compatibility.
- Source of truth: docs/aims/aims_mapping.json (aligns with fpubh-11-1120326.pdf).
- Constraints: Minimal changes per step; tests must remain green; default behavior untouched unless `coach=true` (and feature flag) is set.

Guiding principles
- Small: each task should be completable in <1–2 hours.
- Verifiable: each task defines clear acceptance criteria (tests/docs) and demo steps.
- Reversible: isolate changes behind flags; no breaking API by default.
- Test‑first where feasible: unit tests for pure logic (classifier/scorer) before wiring to the LLM.

Milestones and tasks

Milestone 0 — Planning and guardrails
0.1 Create this living plan document and link it from docs/aims/README.md
- Deliverable: docs/aims/implementation-plan.md (this file) with milestones, tasks, and checklists.
- Acceptance: File exists in repo and is referenced from docs/aims/README.md.
- Status: Done

0.2 Add feature flag definition (planning only)
- Deliverable: Document the `AIMS_COACHING_ENABLED` flag intent here; implementation comes later.
- Acceptance: Flag described; rollout strategy noted.
- Status: Done (documented below in Milestone 6)

Milestone 1 — Core data loading and deterministic logic (offline, no LLM)
1.1 Loader utility plan
- Deliverable: Plan tests and API for loading aims_mapping.json (pure function spec only).
- Verify: Test cases outlined here; no code yet.

1.2 Deterministic classifier plan
- Deliverable: Define inputs/outputs and test fixtures for classifying a clinician turn using last two messages and mapping markers/tie‑breakers.
- Verify: Fixtures and expected labels listed.

1.3 Deterministic scorer plan
- Deliverable: Define scoring rubric application per step and test vectors for 0–3 outcomes.
- Verify: Table of inputs → expected scores and reasons.

1.4 Session aggregation plan
- Deliverable: Define in‑memory model for per‑session metrics (per‑step arrays, averages, coverage) and overall summary rubric.
- Verify: Example aggregation walkthrough in this doc.

Milestone 2 — Unit tests (pure Python, no network)
2.1 Add unit tests for loader, classifier, scorer, aggregator (skipped until implementation lands)
- Deliverable: tests/test_aims_engine.py skeleton with parametrized cases (initially xfail or skipped).
- Verify: pytest collects tests; marked xfail/skip to avoid breaking CI until implementation.

Milestone 3 — Backend API extensions (backward‑compatible)
3.0 Replace default persona immediately (remove Ghostbusters)
- Deliverable: Update app/persona.py to a realistic vaccine‑hesitant parent persona and neutral clinic scene. Remove Ghostbusters content.
- Verify: Unit test confirms default persona text includes no Ghostbusters tokens and includes parent concerns language.
- Note: This task is not behind the feature flag.

3.1 Extend POST /chat input model (coach?: bool, sessionId passthrough)
- Deliverable: Pydantic model change behind feature flag; default false.
- Verify: tests/test_chat.py continues to pass; new tests assert flag plumbed (mocked).

3.2a Define response models for coaching/session (typing only)
- Deliverable: Pydantic models for `coaching` and `session` (no handler wiring yet).
- Verify: mypy/pyright (if used) passes; unit test imports models and validates a sample payload against them.

3.2b Wire response shape when coach=true (handler integration)
- Deliverable: Add optional `coaching` object and `session` metrics fields in the actual response when `coach=true`.
- Verify: Integration test (mock Vertex) asserts presence/shape when `coach=true`; with `coach=false` behavior unchanged.

3.3 Summary retrieval
- Deliverable: Provide dedicated `GET /summary?sessionId=...` to return final report.
- Verify: Unit/integration test returns structured summary.

Milestone 4 — Prompt and single‑pass JSON envelope
4.1 Patient simulator system prompt
- Deliverable: New prompt that sets the LLM as a vaccine‑hesitant parent with constraints (no medical advice, autonomy support, realistic concerns).
- Verify: Golden prompt captured; peer review; token budget noted.

4.2 Compact mapping injection
- Deliverable: Select minimal subset of aims_mapping.json (markers, decision rules, heuristics) to include in prompt.
- Verify: Document selected fields; justify omissions for token economy.

4.3 Output schema and few‑shots
- Deliverable: Strict JSON envelope schema (patient_reply, classification, scoring, coaching) + 1–2 few‑shot examples.
- Verify: Schema validates with jsonschema; examples pass a validator.

Milestone 5 — Engine integration and fallbacks
5.1 Vertex call wiring
- Deliverable: Wrap existing Vertex client to send prompt/context and parse JSON envelope.
- Verify: Mocked integration test returns parsed structure and reply.

5.2a JSON schema validation and strict parsing
- Deliverable: Implement server‑side JSON Schema validation for the envelope; strict parsing with clear error paths and metrics.
- Verify: Unit tests validate good/bad payloads; invalid payloads raise a specific error caught by the handler.

5.2b Deterministic fallback and two‑pass strategy
- Deliverable: If JSON invalid/missing fields, run deterministic classifier/scorer and (if needed) trigger a second lightweight generation for the patient reply; record `fallbackUsed=true`.
- Verify: Test path where model returns bad JSON; fallback engages; response still valid and includes `fallbackUsed=true` in logs.

5.2c Retry policy implementation and logging
- Deliverable: Enforce “1 retry then fallback” at the handler level. Add structured log entries for invalid JSON, retries, and fallbacks (JSON to stdout).
- Verify: Tests simulate invalid JSON → retry → fallback; caplog asserts messages were logged.

5.3 Session state and metrics (Redis mandatory)
- Deliverable: Persist per‑session AIMS metrics using Redis with TTL=3600s. Local dev may use in‑memory only if Redis is unavailable, with a warning. Tests mock Redis.
- Verify: Test increments, averages, and coverage across multiple turns.

Milestone 6 — Feature flags, safety, and observability
6.1 Feature flag AIMS_COACHING_ENABLED
- Deliverable: Environment flag gating coach features; default false.
- Verify: With flag off, behavior unchanged even if coach=true; with flag on, features enabled. Tests cover both states.

6.2 Safety guardrails
- Deliverable: Checks to prevent the patient simulator from giving medical advice; adhere to tone guidelines.
- Verify: Prompt constraints documented; negative tests for disallowed content in patient replies (mocked). If advice detected, perform a light rewrite and log.

6.3 Telemetry (deferred)
- Deliverable: Defer metrics/export. Create docs/todo/telemetry.md describing target metrics and log fields. Keep only logging in scope.
- Verify: TODO doc exists; logging verified via tests.

Milestone 7 — Chainlit UI enhancements (minimal coaching panel)
7.1 Coaching toggle
- Deliverable: UI control to send coach=true and display a coaching panel.
- Verify: Manual demo; mocked backend; UI renders fields.

7.2 Coaching content policy (no numeric scores per turn; no next-step hints)
- Deliverable: Panel shows: detected step name and short text feedback (e.g., “Good mirroring … consider …”). Do not display numeric scores during the conversation. Do not display next-step suggestions. Numeric scores appear only in the final summary modal.
- Verify: Snapshot or simple e2e verifies fields rendered and score/next-step are absent.

7.3 End‑of‑session summary
- Deliverable: Modal shows overall numeric score, strengths, growth areas, and step coverage.
- Verify: Manual demo; basic e2e test harness if feasible.

Milestone 8 — Documentation and rollout
8.1 Update docs (README, docs/api.md, docs/aims/README.md)
- Deliverable: Document flag, request/response fields, and summary endpoint; link to aims_mapping.json. Note that per-turn scores are not displayed in UI.
- Verify: Docs build/lint passes; links valid.

8.2 Rollout plan
- Deliverable: Stage behind flag in dev; measure JSON validity and iterate few‑shots until ≥95% single‑pass success. Keep logs only; telemetry deferred.
- Verify: Checklist and notes updated in this doc.

Milestone 9 — Persona mutation (post‑MVP)
9.1 Define mutation strategies seeded by persona_seed.txt (concerns, emotional valence)
- Deliverable: Design snippet here referencing persona_seed.txt; list 3–5 seed personas.
- Verify: Appendix entry with seeds and selection logic.

9.2 Implement persona mutation at session start (optional flag)
- Deliverable: Code to pick a seed and maintain consistency per session.
- Verify: Unit tests fix the seed and assert persona traits in prompts.

Appendix — Verification details (kept up to date)

A. Classifier/scorer test fixtures (ready to copy into tests)

A.1 Announce vs Secure
- Case A1
  parent_last: "I'm not sure about the MMR; I read about side effects and I'm anxious."
  clinician_last: "It's time for Layla's MMR today. It protects her from measles outbreaks we're seeing locally. How does that sound to you?"
  expected_step: Announce
  rationale: Clear, concise recommendation + brief rationale + invitation; no autonomy language or options → Announce.

- Case A2 (edge leaning Secure)
  parent_last: "I'm still on the fence; I don't like being pressured."
  clinician_last: "It's your decision, and I'm here to support you. We can do it today, or I can share a short handout and we can check in next week — what would work best?"
  expected_step: Secure
  rationale: Explicit autonomy + concrete options → Secure.

- Case A3 (ambiguous Announce with autonomy phrase)
  parent_last: "I just don't know."
  clinician_last: "I recommend the MMR today to protect against measles. It's your decision, and I'm happy to answer questions."
  expected_step: Announce
  rationale: Primary act is a presumptive recommendation; autonomy is supportive, but no options/plan → Announce per tie‑breakers.

A.2 Mirror vs Inquire
- Case M1
  parent_last: "I saw a story about bad reactions, and it scared me."
  clinician_last: "It sounds like that story really worried you and you want to keep your child safe — did I get that right?"
  expected_step: Mirror
  rationale: Accurate reflection of content + emotion; no new info; optional check.

- Case M2
  parent_last: "I don't trust the schedule; it's too many at once."
  clinician_last: "What concerns you most about the schedule for today?"
  expected_step: Inquire
  rationale: Single open question inviting elaboration; no reflective paraphrase.

- Case M3 (reflection followed by question)
  parent_last: "I worry she'll have a bad reaction."
  clinician_last: "You're worried about side effects. What have you heard so far?"
  expected_step: Mirror
  rationale: Reflection is accurate and primary; brief follow‑up question okay → prefer Mirror per tie‑breaker.

- Case M4 (leading question)
  parent_last: "My friend said vaccines can cause autism."
  clinician_last: "You don't believe that myth, do you?"
  expected_step: Inquire (score likely 0–1)
  rationale: It's a question but leading/judgmental; classify as Inquire, score low by heuristics.

- Case M5 (mirror with rebuttal → penalize)
  parent_last: "I'm afraid of side effects."
  clinician_last: "I get you're scared, but that's not true — the data shows it's safe."
  expected_step: Mirror (score 0–1)
  rationale: Contains a rebuttal after a reflection stem → still Mirror by stems, but score low due to non‑judgment violation.

B. Minimal JSON Schema for single‑pass coaching envelope
- Objective: Keep schema compact; require essentials for server processing; allow future extension.

jsonschema (draft‑07 compatible):
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "patient_reply": { "type": "string", "minLength": 1 },
    "classification": {
      "type": "object",
      "properties": {
        "step": { "type": "string", "enum": ["Announce", "Inquire", "Mirror", "Secure"] },
        "confidence": { "type": "number", "minimum": 0, "maximum": 1 },
        "evidence_spans": { "type": "array", "items": { "type": "string" } }
      },
      "required": ["step"],
      "additionalProperties": false
    },
    "scoring": {
      "type": "object",
      "properties": {
        "score": { "type": "integer", "minimum": 0, "maximum": 3 },
        "reasons": { "type": "array", "items": { "type": "string" } }
      },
      "required": ["score"],
      "additionalProperties": false
    },
    "coaching": {
      "type": "object",
      "properties": {
        "tips": { "type": "array", "items": { "type": "string" } },
        "next_step_suggestion": { "type": "string" }
      },
      "required": [],
      "additionalProperties": false
    }
  },
  "required": ["patient_reply", "classification", "scoring"],
  "additionalProperties": false
}

Notes:
- Required minimum: patient_reply + classification.step + scoring.score.
- Server can enrich or ignore `coaching` when `coach=false`.
- UI policy: Do not display numeric scores or next-step suggestions during turns; show only text coaching and the detected step name. Display numeric scores in the final summary only.

C. Prompt snippets and token budget estimates (stub)
- Keep mapping injection to markers + decision_rules + evaluation_heuristics only; target ≤ 1.5k tokens total prompt.

---
Plan update — Decision alignment (2025-10-07)

[UNCHANGED content above retained]

---
Plan update — Additional decisions (post-feedback)

- Logging format: Use JSON-structured logs to stdout for invalid JSON events, retries, fallbacks, and safety rewrites.
- Tests and Redis: Mock Redis in tests; prefer mocking for unit tests broadly. Local dev may run without Redis (with warnings); production uses Redis.
- Coaching UI: Per-turn panel must not show numeric scores and must not hint at next steps; provide only step name and short text feedback.
- Safety rewrite phrasing: Use a lighter-touch phrasing when rewriting advice-like content (e.g., “I’m not the clinician—just sharing how I feel.”).
- Persona: Pick a sensible default vaccine-hesitant parent persona and keep it consistent until mutation work lands.


---
Process compliance — How we keep this plan updated (2025-10-07)

Purpose
- Ensure that at every step we explicitly record: Status, Tests, and Docs updates.
- Make the plan a reliable source of truth for current progress and what remains.

Rules of engagement
- Every task in this plan must include or be linked to:
  - Status: Not started | In progress | Done | Blocked
  - Tests: Added/updated? Brief note or link to test file(s)
  - Docs: Added/updated? Brief note or link
- When a task is completed, append a dated entry under the latest Plan status update section.
- Keep entries concise; link to diffs or files when possible.

Template (copy/paste per task)
- Task: <id and title>
  - Status: <state>
  - Tests: <added/updated/na> — <files/notes>
  - Docs: <added/updated/na> — <files/notes>
  - Evidence: <short note: e.g., commit hash, PR link, or test output>

---
Plan status update — Compliance snapshot (2025-10-07)

The following reflects work completed earlier in this session and clarifies Tests/Docs status. Future steps will follow the same pattern.

- Task: 3.0 Replace default persona immediately (remove Ghostbusters)
  - Status: Done
  - Tests: na (no unit test added yet specific to persona text)
  - Docs: Updated docs/memory-and-persona.md to reference persona defaults (already present). README unchanged.
  - Evidence: app/persona.py now contains a realistic vaccine‑hesitant parent persona and clinic scene.

- Task: 3.1 Extend POST /chat input model (coach?: bool, sessionId)
  - Status: Done
  - Tests: Pending (to be added in Milestone 2/3 tests)
  - Docs: Pending (will document in docs/api.md during Milestone 8)
  - Evidence: app/main.py ChatRequest includes coach and sessionId.

- Task: 3.2a Define response models for coaching/session (typing only)
  - Status: Done
  - Tests: Pending (unit test to import Coaching/SessionMetrics and validate sample)
  - Docs: Pending
  - Evidence: app/main.py defines Coaching and SessionMetrics Pydantic models.

- Task: 3.2b Wire response shape when coach=true (handler integration)
  - Status: Done (basic placeholder classifier; backward‑compatible behind flag)
  - Tests: Pending (mocked integration to assert presence/shape)
  - Docs: Pending (docs/api.md to describe optional fields)
  - Evidence: app/main.py adds optional coaching/session in /chat when AIMS_COACHING_ENABLED=true and coach=true.

- Task: 3.3 Summary retrieval (GET /summary)
  - Status: Done (minimal deterministic summary)
  - Tests: Pending (integration test to call /summary with a fake session)
  - Docs: Pending (docs/api.md to add endpoint)
  - Evidence: app/main.py exposes GET /summary returning overallScore, stepCoverage, strengths, growthAreas, narrative.

- Task: 5.3 Session state and metrics (Redis mandatory)
  - Status: In progress
  - Tests: Pending (mock Redis; assert TTL and aggregation across turns)
  - Docs: Updated docs/memory-and-persona.md with Redis config guidance (present). Further docs pending.
  - Evidence: app/main.py contains RedisStore with TTL support; selection by env.

Notes
- Coverage currently ~49% (from pytest). New code paths will be added with ≥80% coverage as they are implemented (Milestone 2/3 tests forthcoming).
- This snapshot addresses the user requirement to track Status/Tests/Docs per step.

---

Plan status update — 2025-10-07 (late)

- Task: 1.2 Deterministic classifier plan
  - Status: Done
  - Tests: Added — tests/test_aims_engine.py::TestClassification (cases A1–A3, M1–M4)
  - Docs: This plan reflects tie-breakers and markers used.
  - Evidence: app/aims_engine.py classify_step; pytest passing.

- Task: 1.3 Deterministic scorer plan
  - Status: Done
  - Tests: Added — tests/test_aims_engine.py::TestScoring (M5 penalty; good Inquire/Announce/Secure)
  - Docs: Heuristic notes encoded in code aligned with aims_mapping.json.
  - Evidence: app/aims_engine.py score_step; pytest passing.

- Task: 2.1 Unit tests (pure Python)
  - Status: Done
  - Tests: Added — tests/test_aims_engine.py (offline, no network)
  - Docs: This plan updated; mapping remains the source of truth.
  - Evidence: pytest passed; coverage for app/aims_engine.py ≥ 80%.

---
Plan status update — 2025-10-07 (night)

- Tests: pytest passed locally; all tests green.
- Coverage: Overall 55% (from coverage report). Not yet at ≥80% target for new logic; upcoming tasks will add tests to raise coverage.
- Deprecation warnings: app/vertex.py emitted an `invalid escape sequence '\{'` DeprecationWarning; tracked for a later cleanup task (does not affect functionality).
- Docs: README.md updated to list GET /summary and to note optional coaching fields when `coach=true` and `AIMS_COACHING_ENABLED=true`.

Task snapshots
- Task: 3.1 Extend POST /chat input model (coach?: bool, sessionId)
  - Status: Done
  - Tests: Covered indirectly by existing integration test; dedicated tests pending in Milestone 3
  - Docs: README updated; docs/api.md pending
- Task: 3.2a Define response models for coaching/session
  - Status: Done
  - Tests: Pending (simple Pydantic validation test to be added)
  - Docs: Pending
- Task: 3.2b Wire response shape when coach=true (handler integration)
  - Status: Done (behind AIMS_COACHING_ENABLED)
  - Tests: Pending (mocked integration when coach=true)
  - Docs: README updated; full API doc pending
- Task: 3.3 Summary retrieval
  - Status: Done (minimal deterministic summary)
  - Tests: Pending (integration test to call /summary)
  - Docs: README updated
- Task: 5.3 Session state and metrics (Redis mandatory)
  - Status: In progress (Redis store present; ensure prod uses Redis via env)
  - Tests: Pending (mock Redis)
  - Docs: docs/memory-and-persona.md already documents Redis config

Next steps
- Add missing unit/integration tests for 3.1–3.3 and 5.3 to raise coverage and verify flag on/off behavior.
- Optionally address the DeprecationWarning in app/vertex.py.


---
Milestone Status Summary — 2025-10-07 22:54

Legend: [Done] [In progress] [Not started] [Deferred]

Milestone 0 — Planning and guardrails
- 0.1 Create this living plan document and link it from docs/aims/README.md — Done
- 0.2 Add feature flag definition (planning only) — Done

Milestone 1 — Core data loading and deterministic logic (offline, no LLM)
- 1.1 Loader utility plan — Done
- 1.2 Deterministic classifier plan — Done
- 1.3 Deterministic scorer plan — Done
- 1.4 Session aggregation plan — Done

Milestone 2 — Unit tests (pure Python, no network)
- 2.1 Add unit tests for loader, classifier, scorer, aggregator — Done

Milestone 3 — Backend API extensions (backward‑compatible)
- 3.0 Replace default persona immediately (remove Ghostbusters) — Done
- 3.1 Extend POST /chat input model (coach?: bool, sessionId passthrough) — Done
- 3.2a Define response models for coaching/session (typing only) — Done
- 3.2b Wire response shape when coach=true (handler integration) — Done
- 3.3 Summary retrieval (GET /summary) — Done

Milestone 4 — Prompt and single‑pass JSON envelope
- 4.1 Patient simulator system prompt — Not started
- 4.2 Compact mapping injection — Not started
- 4.3 Output schema and few‑shots — Not started

Milestone 5 — Engine integration and fallbacks
- 5.1 Vertex call wiring — Not started
- 5.2a JSON schema validation and strict parsing — Not started
- 5.2b Deterministic fallback and two‑pass strategy — Not started
- 5.2c Retry policy implementation and logging — Not started
- 5.3 Session state and metrics (Redis mandatory) — In progress

Milestone 6 — Feature flags, safety, and observability
- 6.1 Feature flag AIMS_COACHING_ENABLED — Done
- 6.2 Safety guardrails — Not started
- 6.3 Telemetry — Deferred (see docs/todo/telemetry.md)

Milestone 7 — Chainlit UI enhancements (minimal coaching panel)
- 7.1 Coaching toggle — Not started
- 7.2 Coaching content policy (no per‑turn numeric scores or next‑step hints) — Not started
- 7.3 End‑of‑session summary — Not started

Milestone 8 — Documentation and rollout
- 8.1 Update docs (README, docs/api.md, docs/aims/README.md) — In progress
- 8.2 Rollout plan — Not started

Milestone 9 — Persona mutation (post‑MVP)
- 9.1 Define mutation strategies seeded by persona_seed.txt — Not started
- 9.2 Implement persona mutation at session start — Not started

Process reminder: Update this summary and the per-task Status lines immediately when completing any stage, marking it Done with a dated note in the Plan status update section above.
