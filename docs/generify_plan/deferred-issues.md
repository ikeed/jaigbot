# Generify Deferred Issues

This file records issues intentionally deferred during the modularization
phases so they do not get lost.

## Phase 2

None currently.

## Phase 3

- `ChatOrchestrator.__init__` still has a defensive registry/settings fallback
  for direct-construction and non-lifespan code paths. Consolidate active-module
  resolution to one authoritative path once later phases finish moving startup,
  resume, and tests onto app-state or explicit dependency injection.
- The old legacy chat path now runs behind `AimsTrainingModule.handle_turn(...)`
  instead of in core, but it is not yet represented as its own compatibility
  module. Revisit that split once session/resume and storage ownership are
  module-aware enough to support a second runtime module cleanly.

## Phase 4

- Chainlit startup and UI rendering still assume an AIMS-style scenario-card
  experience (`initialCard`, persona naming, `present_scenario_card(...)`).
  The ownership seam is better now because `/session` is module-owned, but the
  frontend-facing bootstrap vocabulary is still compatibility-shaped and should
  be generalized in Phase 6.
