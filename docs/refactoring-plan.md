# JaigBot Refactoring Plan (Prioritized)

Status: Approved by maintainer • Last updated: 2025-10-11 19:11 local

Executive summary
- Goal: Improve maintainability, testability, and separation of concerns while preserving current behavior and API contracts.
- Strategy: Extract cohesive services from app/main.py, standardize logging/error handling, introduce a light configuration module, and remove client duplication in Chainlit. Use dependency injection (DI) and small, testable modules. Keep changes incremental and well covered by tests.
- Guiding principle: Behavior parity first, architecture improvements second. Lock current behavior with tests before large moves.

Scope and non-goals
- In-scope: Internal refactors, structure, DI, logging/error shape standardization, Chainlit helper dedupe, typed settings, constants extraction.
- Out-of-scope (for now): New features, public API shape changes, switching LLM provider, streaming APIs, or major UX changes.

Key risks and mitigations
- Silent behavior drift: Add/expand unit tests before extraction, preserve response contracts in tests (tests/test_chat.py and related files).
- Over-abstraction: Extract only established seams; prefer a single VertexGateway over heavy factory hierarchies.
- Logging/PII: Keep caps (SAFETY_LOG_CAP) and request/response previews; centralize scrubbing in telemetry util.

Acceptance criteria (global)
- All existing pytest tests pass locally and in CI after each phase.
- POST /chat contract remains unchanged (see docs/api.md). Coaching gated by env + request.
- Log events consistently include requestId and sessionId (where available) and respect size caps.
- The chat() function in app/main.py is substantially reduced in size and complexity, with core logic moved into services.

Phased plan (priority and sequence)

Phase 0 — Test safety net and docs (High, 1–2 days)
- Tasks:
  - Add/confirm high-level tests pinning current /chat behavior for legacy and coaching paths, error cases, model fallback, session cookie behavior.
  - Document current response shapes in docs/api.md if gaps exist.
- Deliverables:
  - Additional tests under tests/ (if needed) and any doc touch-ups.

Phase 1 — Conversation/security/telemetry extraction (High, 3–5 days)
- Intent: Reduce chat() cyclomatic complexity without changing behavior.
- Tasks:
  - Create app/services/conversation_service.py with: history formatting, recent context selection, concern extraction, advice pattern detection, topic detection, and any non-HTTP conversation utilities.
  - Create app/security/jailbreak.py with jailbreak/meta detection helpers currently defined inside chat().
  - Create app/telemetry/events.py with log_event() and constants for event shapes and caps; route existing logging through it.
  - Wire chat() to use these modules; leave HTTP request/response orchestration in the FastAPI layer.
- Deliverables:
  - Smaller chat() function, new units with focused tests.

Phase 2 — Vertex gateway and JSON enforcement (High, 2–3 days)
- Intent: Remove duplicated fallback loops for reply/classifier and make Vertex usage easy to mock.
- Tasks:
  - Create app/services/vertex_gateway.py encapsulating model fallback and typed methods:
    - generate_text_json(prompt, schema, system_instruction, temperature, max_tokens)
    - generate_text(prompt, system_instruction, temperature, max_tokens)
  - Move duplicate loops from _vertex_call and _vertex_call_json to gateway; ensure consistent fallback logging events.
  - Unit tests simulating failures to verify fallback order and event logging.
- Deliverables:
  - One gateway abstraction, simplified chat() helpers, tests for fallbacks.

Phase 3 — Session service extraction (Medium→High, 2–3 days)
- Intent: Separate cookie/session/memory orchestration from business logic; improve testability.
- Tasks:
  - Create app/services/session_service.py handling: get_or_create_session(request), load_history, append_turn, trim_history, TTL, and cookie options.
  - Replace direct _MEMORY_STORE access and cookie header manipulation in chat() with this service.
  - Add unit tests independent of FastAPI for trimming/TTL and cookie flags.
- Deliverables:
  - SessionService in place; chat() no longer manipulates cookies/history directly.

Phase 4 — Config module and DI (Medium, 1–2 days)
- Intent: Centralize typed configuration and decouple env reads from main.
- Tasks:
  - Introduce app/config.py (Pydantic BaseSettings or dataclass) with: PROJECT_ID, REGION, VERTEX_LOCATION, MODEL_ID, TEMPERATURE, MAX_TOKENS, MODEL_FALLBACKS, logging caps/flags, memory/cookie settings, AIMS flags, etc.
  - Instantiate once at startup (app.state.settings) and inject into services. Maintain existing env var names and defaults.
  - Light validation: PROJECT_ID required for live Vertex; cookie security in dev vs prod; numeric bounds.
- Deliverables:
  - All env access goes through Settings; tests can inject alternative settings.

Phase 5 — Error handling and logging standardization (Medium, 1–2 days)
- Intent: Uniform error responses and structured logs.
- Tasks:
  - Define a single error response schema { code, message, details? } and ensure FastAPI exception handlers produce it consistently.
  - Ensure logs include requestId, sessionId, modelId when available; maintain SAFETY_LOG_CAP and body/response preview caps.
  - Tests for handlers and representative failure paths.
- Deliverables:
  - Consistent error responses and logs across endpoints.

Phase 6 — Chainlit cleanup (Medium, ~1 day)
- Intent: Remove duplication and make the UI glue thinner.
- Tasks:
  - Deduplicate _pick_avatar and _abs_existing in chainlit_app.py into a single helper (module-level or a tiny app/ui/avatars.py helper).
  - Optional: Add a tiny client SDK wrapper for POST /chat if it reduces coupling (keep minimal).
- Deliverables:
  - Single source of truth for avatar helpers; no functional changes.

Phase 7 — Constants, enums, and signatures (Low, 1–2 days, ongoing)
- Intent: Improve readability with minimal behavior risk.
- Tasks:
  - Extract regexes, magic numbers, and repeated strings to app/constants.py or enums.
  - Introduce small Pydantic models or dataclasses for complex payloads in services (e.g., AIMS results), keeping API layer stable.
- Deliverables:
  - Cleaner signatures and centralized constants.

Work items and acceptance criteria
- W1: conversation_service.py with unit tests for history formatting, concern extraction, advice detection. AC: chat() shrinks by ~300–400 lines without behavior change; tests pass.
- W2: vertex_gateway.py with fallback logic and tests for retry/fallback logging. AC: No duplicated model iteration; events standardized.
- W3: session_service.py replacing cookie/memory logic in chat(). AC: Behavior parity verified by session tests; chat() does not touch _MEMORY_STORE directly.
- W4: config.Settings injected via app.state.settings; env parsing removed from top of main.py. AC: Backward-compatible env names; tests can override.
- W5: Error/logging standardization. AC: All endpoints return { code, message, details? } on errors; logs include requestId/sessionId and respect caps.
- W6: Chainlit helper dedupe. AC: One _pick_avatar implementation; identical behavior.
- W7: Constants/enums and signature cleanup. AC: No behavior change; improved readability.

Team roles and coordination
- Solo-friendly, but if multiple contributors:
  - Owner A: Phases 1–3
  - Owner B: Phases 4–5
  - Owner C: Phase 6–7
- Weekly check-ins: Verify phases don’t drift; gate Phase 2 on Phase 1 tests passing, etc.

Testing strategy
- Always run pytest locally before committing changes (see pytest.ini for coverage on app/).
- Mock Vertex calls (existing tests already do). Add targeted unit tests for new services.
- Keep tests fast and offline-capable. Do not rely on live PROJECT_ID for unit tests.

Migration and rollout
- Refactor behind the same API; no client changes required.
- Merge phases incrementally; avoid large PRs. Each PR must pass tests and include brief docs if behavior changes.

Progress tracker
- Phase 2 — Vertex gateway and JSON enforcement: ✓ Completed (VertexGateway implemented; main.py delegates; tests passing locally)
- W2 — Vertex fallback refactor: ✓ Completed
- Phase 1 — Conversation/security/telemetry extraction: ✓ Completed
  - Create security/jailbreak helpers module: ✓ Initial module created (wired into main for jailbreak checks)
  - Create telemetry/events module: ✓ Implemented and wired (log_event, truncate_for_log)
  - Extract conversation utilities: ✓ Implemented and wired (delegated from main)
  - Prune dead wrappers from main.py: ✓ Completed (removed _concern_topic, _canon, _is_duplicate_concern, _topics_in, _mark_best_match_mirrored)
- Phase 3 — Session service extraction: not started
- Phase 4 — Config module and DI: not started
- Phase 5 — Error/logging standardization: not started
- Phase 6 — Chainlit cleanup: not started
- Phase 7 — Constants/enums/signatures: not started

Appendix: Pushback incorporated
- Config was centralized but tied to main.py — moving to app/config.py for DI and testing, not because it was scattered.
- Avatar registration duplication is a maintainability issue, not a runtime hot path; still worth cleaning up.
- Prefer a single VertexGateway over heavy factory patterns; keep it simple and testable.
