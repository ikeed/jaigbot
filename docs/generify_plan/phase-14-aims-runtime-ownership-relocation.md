# Phase 14: AIMS Runtime Ownership Relocation

## Status

Implemented.

## Objective

Finish the physical ownership move for the remaining AIMS-specific runtime
services so the generic core no longer points contributors back into
`app/services/` for AIMS domain behavior.

At the end of this phase:

- the remaining AIMS runtime services live under `app/modules/aims/services/`
- the AIMS module imports its own owned runtime paths directly
- AIMS docs and contributor guidance point to the owned module paths

## Why This Phase Exists

By the end of Phase 13, the architecture was already generic, but several
clearly AIMS-owned services still lived under `app/services/`:

- `aims_coaching_handler.py`
- `aims_dependencies.py`
- `aims_endgame_service.py`
- `aims_state_service.py`
- `aims_turn_coordinator.py`
- `aims_turn_telemetry.py`
- `legacy_chat_handler.py`
- `coach_feedback_history_service.py`
- `coach_post.py`

That was no longer a shim issue. It was an ownership gap against the original
goal that all AIMS-specific behavior should live in the AIMS module.

## Scope

### In Scope

- physical relocation of remaining AIMS-owned runtime services
- import rewiring in app code and tests
- AIMS runtime map and contributor guide updates

### Out Of Scope

- generic core behavior changes
- archive/schema changes
- branding/asset renaming

## Implementation Plan

1. Move the remaining AIMS-owned runtime files under
   `app/modules/aims/services/`.
2. Rewire app imports to the owned paths.
3. Rewire tests and monkeypatch targets to the owned paths.
4. Update `AGENTS.md` and `docs/aims/README.md` so the documented ownership
   model matches the code.
5. Re-run focused AIMS service tests, then the full non-integration suite.

## Risks

### Risk 1: Import churn breaks test monkeypatch targets

Mitigation:

- update monkeypatch paths in the same change set as the move
- run the AIMS-focused regression ring first

### Risk 2: “Legacy” handler ownership becomes ambiguous

Mitigation:

- treat `LegacyChatHandler` as AIMS-owned for now because it is only reachable
  through `AimsTrainingModule.handle_turn(...)`
- keep any future split into a dedicated compatibility module as a separate
  follow-up phase

### Risk 3: Docs continue to route contributors to old paths

Mitigation:

- update the agent guide and the AIMS runtime map as part of the same phase

## Verification

- `git diff --check`
- `.venv/bin/python -m compileall -q app tests`
- focused pytest ring for moved AIMS services and module dispatch
- full non-integration suite

## What Landed

- moved the remaining AIMS-owned runtime services under
  `app/modules/aims/services/`:
  - `aims_coaching_handler.py`
  - `aims_dependencies.py`
  - `aims_endgame_service.py`
  - `aims_state_service.py`
  - `aims_turn_coordinator.py`
  - `aims_turn_telemetry.py`
  - `legacy_chat_handler.py`
  - `coach_feedback_history_service.py`
  - `coach_post.py`
- rewired app imports and test imports to the owned module paths
- updated AIMS runtime ownership docs in `docs/aims/README.md`
- updated `AGENTS.md` so “read first” guidance points at the actual owned
  module paths

## Residual Issues

- the fallback-oriented `LegacyChatHandler` is now physically owned by AIMS,
  but it is still conceptually a compatibility path hidden inside the AIMS
  module rather than a separate compatibility module
- several shared static asset names still use AIMS-era naming even though the
  runtime ownership model is now much cleaner
