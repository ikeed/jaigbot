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
  summary payload shape in the repo. Phase 8 should prove the "no summary
  capability" path with a second stub module rather than assuming the seam is
  complete because AIMS works.

## Phase 6

- Module-owned frontend CSS is not actually loaded through the manifest yet.
  `frontendCss` is exposed via `/config`, but Chainlit still serves one
  deployment-level `custom_css` entrypoint. Phase 8 should decide whether CSS
  remains one shell asset with module sections or becomes manifest-driven like
  JS bundles.
- The AIMS message-role renderer is now module-owned logically, but it still
  lives at `public/js/aimsbot/message-roles.js`. Phase 7 should relocate that
  file under an AIMS-owned frontend path so the physical layout matches the
  ownership boundary.
- Browser-based local verification could not be completed in this environment:
  the in-app browser runtime had no active `iab` instance, and fallback
  Playwright verification could not launch because the required local browser
  runtime was unavailable here. Re-run a real browser sanity check in a normal
  local developer session before treating Phase 6 as fully field-verified.
