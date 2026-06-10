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

## Phase 5

- `StorageService._transform_to_logical_schema(...)` resolves archives without
  a persisted `module_id` through the deployment's active module. That is
  correct for the current one-module-per-deployment runtime, but mixed-module
  buckets or cross-deployment archive readers will need an explicit legacy
  adapter strategy before multiple modules write into the same archive space.
- Summary capability is now module-owned, but there is still only one concrete
  rich summary payload shape in the repo. Phase 8 proved that the "no summary
  capability" path works, but it did not add a second fully featured summary
  schema to exercise cross-module reporting semantics.

## Phase 6

- Module-owned frontend CSS is not actually loaded through the manifest yet.
  `frontendCss` is exposed via `/config`, but Chainlit still serves one
  deployment-level `custom_css` entrypoint. Phase 8 left that unresolved:
  decide later whether CSS remains one shell asset with module sections or
  becomes manifest-driven like JS bundles.
- Browser-based local verification could not be completed in this environment:
  the in-app browser runtime had no active `iab` instance, and fallback
  Playwright verification could not launch because the required local browser
  runtime was unavailable here. Re-run a real browser sanity check in a normal
  local developer session before treating Phase 6 as fully field-verified.

## Phase 7

- The AIMS-prefixed orchestration/state cluster still lives under
  `app/services/`:
  - `aims_coaching_handler.py`
  - `aims_dependencies.py`
  - `aims_endgame_service.py`
  - `aims_state_service.py`
  - `aims_turn_coordinator.py`
  - `aims_turn_telemetry.py`
  This is intentional. Moving that cluster now would enlarge the touched
  surface without improving any already-proven seam. Revisit it only if a later
  phase needs stricter physical ownership or if a second module demonstrates a
  real collision.
- Compatibility shims still exist at the old import paths for the moved AIMS
  engine, prompt module, and several generic-named services. Phase 8 proved the
  architecture without removing them; they should be retired only when
  downstream imports, test ownership, and docs are cleaned up deliberately.

## Phase 8

- `ChatContextBuilder` still computes `person_last` only from the `assistant`
  role. The interview proof module does not need that field, but a future
  richer non-AIMS module may. Generalize that helper only when a real module
  requires it; otherwise it is churn.
- UI author/label mapping is still largely AIMS-first. Core frontend code can
  load different module bundles now, but `app/chat_roles.py` and the generic
  history-format helpers still assume the default `user`/`assistant`/`coach`
  set. The interview stub proves routing and bootstrap, not polished multi-role
  rendering.
- Session bootstrap transport is still compatibility-shaped around
  `character`, `scene`, `personaName`, and `initialCard`. The generic
  `SessionBootstrapPayload` exists, but the outward JSON contract still favors
  the AIMS shell.
- Deployment-level branding is still partially AIMS-specific:
  FastAPI `APP_TITLE`, login/duplicate templates, avatar asset titles, and some
  docs continue to say `AIMSBot`. The active module now controls Chainlit
  profile/loading branding, but shell-level branding cleanup remains a separate
  product decision.
