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
  frontend-facing bootstrap vocabulary is still compatibility-shaped and will
  need another pass only if a future module needs a meaningfully different
  startup shell.

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

- Browser-based local verification could not be completed in this environment:
  the in-app browser runtime had no active `iab` instance, and fallback
  Playwright verification could not launch because the required local browser
  runtime was unavailable here. Re-run a real browser sanity check in a normal
  local developer session before treating Phase 6 as fully field-verified.

## Phase 7

None currently.

## Phase 9

- The generic bootstrap transport now carries a first-class `module` block with
  `participantContext`, `state`, and plural `artifacts`, but the Chainlit shell
  still treats the first artifact as the one renderable startup surface. That
  is good enough for the current shell, not a finished multi-artifact UI model.

## Phase 10

- The shell title is now generic, but the shared logo asset path remains
  `/public/aimsbot.png` and several internal static asset names still use the
  old AIMSBot naming. That is acceptable for now, but it is still branding
  debt.
- Generic product docs and `AGENTS.md` were updated, but AIMS-specific docs
  still intentionally dominate the repo. That is correct while AIMS remains the
  primary shipped module, but a future broader module rollout will need another
  documentation pass.

## Phase 11

- Direct construction still falls back to the cached built-in runtime when an
  explicit `active_module` is not supplied. That is a bounded fallback now, not
  a registry rebuild path, but it is still transitional.
- Legacy-module inference is now explicit, but it only recognizes historical
  AIMS data families. That is the right move for this repo today, but it is not
  a general cross-module migration system.

## Phase 12

- Startup-artifact presentation is now explicit and multi-artifact aware, but
  the shell model is still intentionally narrow: one primary artifact plus
  inline cards, with passive artifacts ignored until a later module needs a
  richer layout contract.
- Local frontend verification here reached the served `/api/config` payload and
  the `/chat` bootstrap asset wiring, but a full Playwright-driven browser pass
  could not run because the required local browser runtime was unavailable in
  this environment.
- Shared avatar and logo asset ownership is still shell-level, and several
  asset filenames remain AIMS-named even though the browser role-label logic is
  now generic.

## Phase 13

- Historical planning and cleanup docs still mention some pre-move file paths
  intentionally as transition context. Those references are now marked
  historical, but the repo still carries that historical narrative in docs.

## Phase 14

- `LegacyChatHandler` is now physically owned by AIMS, but it is still a
  compatibility-oriented path hidden inside the AIMS module instead of a
  dedicated compatibility module or a truly generic fallback module.
- Several shared static assets and file names are still AIMS-era even though
  the runtime ownership move is complete:
  - `/public/aimsbot.png`
  - several avatar file names
  - some internal JS/CSS naming
