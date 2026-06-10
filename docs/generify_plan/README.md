# Generify Plan

## Purpose

This directory breaks the generification effort into the full implementation
sequence:

1. contract and static registry
2. generic request/response envelope and module-facing schema seam
3. orchestrator dispatch through the active module
4. session/bootstrap/history and resume generalization
5. storage/archive/summary modularization
6. frontend shell and UI message modularization
7. AIMS relocation and core cleanup
8. config/branding/test reorganization and second-module proof

The goal is to let implementation proceed incrementally without forcing
backtracking in storage, resume, or frontend work that will come later.

## Documents

- [Phase 1: Contract And Registry](./phase-1-contract-and-registry.md)
- [Phase 2: Generic Envelope And Schema Decoupling](./phase-2-generic-envelope-and-schema-decoupling.md)
- [Phase 3: Orchestrator Dispatch](./phase-3-orchestrator-dispatch.md)
- [Phase 4: Session And Resume Generalization](./phase-4-session-and-resume-generalization.md)
- [Phase 5: Storage And Summary Modularization](./phase-5-storage-and-summary-modularization.md)
- [Phase 6: Frontend Shell Modularization](./phase-6-frontend-shell-modularization.md)
- [Phase 7: AIMS Relocation And Core Cleanup](./phase-7-aims-relocation-and-core-cleanup.md)
- [Phase 8: Config, Tests, And Second-Module Proof](./phase-8-config-tests-and-second-module-proof.md)

## Current Status

### Phase 1

Implemented.

Actual artifacts now present in the repo:

- `app/core/module_types.py`
- `app/core/interfaces.py`
- `app/core/registry.py`
- `app/modules/aims/module.py`
- additive `ACTIVE_MODULE` config
- startup-time registry construction and active-module resolution
- additive active-module exposure in `/config` and `/diagnostics`

Implication for later phases:

- active-module resolution is no longer theoretical
- the AIMS adapter exists, but is still metadata-first
- later phases should extend that adapter rather than bypass it

### Phase 2

Implemented.

Actual artifacts now present in the repo:

- `app/core/response_types.py`
- `app/core/response_serialization.py`
- additive `moduleId` and `moduleOptions` request fields in `app/models.py`
- module-owned response shaping in `app/modules/aims/module.py`
- `ChatOrchestrator` response construction routed through
  `active_module.format_module_response(...)`
- `app/main.py` passes the resolved active module into the orchestrator

Implication for later phases:

- a generic internal response envelope now exists
- outward API compatibility aliases still come from one serializer layer
- Phase 3 should move turn execution through the module contract, not invent a
  second response abstraction
- there is still a temporary registry/settings fallback in
  `ChatOrchestrator.__init__`; Phase 3 should consolidate resolution ownership
  and remove duplicate fallback logic where safe

### Phase 3

Implemented.

Actual artifacts now present in the repo:

- `ChatOrchestrator.handle_chat(...)` dispatches through one module turn path
- `AimsTrainingModule.handle_turn(...)` owns the coaching-vs-legacy execution
  choice for the active AIMS module
- module-owned archive shaping via `build_archive_payload(...)` is now the seam
  between domain endgame state and core background uploads
- outward response shaping remains centralized in
  `format_module_response(...)`

Implication for later phases:

- session/bootstrap/resume work in Phase 4 can extend the same AIMS adapter
  that now owns runtime turn handling
- storage work in Phase 5 should build on `build_archive_payload(...)` instead
  of reintroducing AIMS-specific archive assembly in core
- one intentional transitional compromise remains: legacy chat behavior is
  hidden behind the AIMS module rather than modeled as a separate module

### Phase 4

Implemented.

Actual artifacts now present in the repo:

- generic session bootstrap types in `app/core/session_types.py`
- compatibility serialization for module-owned session bootstrap in
  `app/core/session_serialization.py`
- `/session` now delegates to `active_module.initialize_session(...)`
- runtime session memory now records `module_id`
- history trimming/counting seams accept module-counted roles
- current-thread persistence and resume validation are module-aware

Implication for later phases:

- Phase 5 can persist `module_id` and module-shaped archive/session envelopes
  without inventing a new bootstrap seam
- Phase 6 should replace the remaining scenario-card-specific UI vocabulary
  rather than trying to rebuild session bootstrap from scratch

### Phase 5

Implemented.

Actual artifacts now present in the repo:

- generic archive envelope types in `app/core/archive_types.py`
- archive serialization in `app/core/archive_serialization.py`
- module-owned archive-envelope shaping via
  `AimsTrainingModule.build_archive_envelope(...)`
- `StorageService` now writes through the active module's archive envelope
  instead of hardcoding AIMS analytics/config fields in core
- `/summary` now delegates through `active_module.build_summary(...)`
- archive/persona readers were updated to read persona names from the new
  generic `module.participantContext` block as well as the legacy AIMS shape

Implication for later phases:

- Phase 6 can treat frontend modularization as an asset/event problem rather
  than a backend summary/bootstrap problem
- Phase 7 should move remaining AIMS archive/summary helpers behind
  module-owned paths instead of rebuilding these seams
- Phase 8 still needs a non-AIMS proof that "summary unsupported" and
  mixed-role/mixed-startup modules behave cleanly

## Cross-Phase Rules

These rules apply across all remaining phases.

### 1. Preserve behavior until Phase 3 is complete

Phase 1 and Phase 2 are architecture phases. They should not change runtime
chat behavior except for low-risk diagnostics and compatibility wrappers.

### 2. Do not move AIMS files early

Relocation is not part of the first three phases. The AIMS implementation
should stay where it is and be wrapped, adapted, or called through seams until
dispatch is stable.

### 3. Do not change persistence shape in these phases

The first three phases must prepare for:

- module-aware Redis prefixes
- module-aware archive schemas
- module-aware session resume

but should not yet migrate those shapes. The contract must expose the metadata
needed for that later work.

### 4. Treat `module_id` as a first-class concept from Phase 1 onward

Even before sessions or archives persist it, the architecture must assume that:

- every conversation belongs to one module
- module resolution will eventually come from more than deployment config
- resume must never silently cross module boundaries

### 5. Prevent hidden AIMS language in core

Core abstractions created in these phases must avoid domain words such as:

- vaccine
- patient
- clinician
- coach
- persona

unless they are clearly module-local.

### 6. Prefer explicit construction over import magic

Registry construction, module registration, and module resolution should be
deterministic and testable. Do not use dynamic discovery yet.

## Handoff Boundaries

### Phase 1 -> Phase 2

Phase 2 may assume:

- a stable `TrainingModule` contract exists
- a registry can resolve the active module
- AIMS has a thin module adapter and manifest
- startup/config surfaces already expose active-module metadata

Phase 2 must not assume:

- chat dispatch already goes through modules
- storage is already module-aware
- frontend assets are already loaded from manifests

### Phase 2 -> Phase 3

Phase 3 may assume:

- core has a generic response envelope or a compatibility wrapper that can hold
  module-produced payloads
- AIMS has a module adapter and a clear place to add turn-handling behavior
  without moving all files
- active-module resolution is already explicit
- response formatting already flows through `active_module.format_module_response(...)`

Phase 3 must still avoid:

- archive migration
- Redis key migration
- frontend shell modular loading

### Phase 3 -> Phase 4

Phase 4 may assume:

- core chat dispatch already routes through the active module
- module adapters can now own startup/resume/session semantics incrementally
- module-owned archive shaping already exists for AIMS endgame exports

Phase 4 must still avoid:

- storage key migration
- archive schema migration
- frontend bundle splitting

### Phase 4 -> Phase 5

Phase 5 may assume:

- session and resume semantics have a module-owned seam
- `module_id` handling rules are explicit for runtime memory and thread state
- AIMS endgame archive payload shaping already lives behind a module hook
- `/session` bootstrap is already module-owned, even though its outward fields
  remain compatibility-shaped

### Phase 5 -> Phase 6

Phase 6 may assume:

- storage/archive payloads can carry module metadata cleanly
- module manifests are stable enough to drive frontend asset manifests

### Phase 6 -> Phase 7

Phase 7 may assume:

- the shell is no longer forced to import AIMS-specific frontend or startup logic
- backend runtime behavior is already routed through module seams

### Phase 7 -> Phase 8

Phase 8 may assume:

- AIMS can live under module-owned boundaries without core orchestration imports
- remaining work is largely cleanup, migration-proofing, and extensibility proof

## Review Summary

These phase plans were reviewed together against the current codebase to avoid
the main failure modes:

1. Phase 1 accidentally freezing AIMS-shaped request/response contracts
2. Phase 2 changing API semantics before dispatch is ready
3. Phase 3 routing chat through modules before compatibility envelopes exist
4. Phase 4 trying to solve storage migration while resume semantics are still unstable
5. Phase 5 migrating archives before session/module ownership is explicit
6. Phase 5 adding a generic archive shell without keeping compatibility readers
7. Phase 5 summary delegation landing before there is a module-owned seam
6. Phase 6 modularizing frontend assets before manifests and message vocabulary are stable
7. Phase 7 relocating AIMS files before runtime seams are proven

The sequence below is intentional:

- Phase 1 defines metadata and ownership
- Phase 2 defines transport and payload seams
- Phase 3 switches control flow
- Phase 4 switches session and resume ownership boundaries
- Phase 5 switches persistence and summary ownership boundaries
- Phase 6 switches frontend shell ownership boundaries
- Phase 7 moves AIMS physically and removes residual core coupling
- Phase 8 proves the architecture with a second module and cleans up drift

That order minimizes rework and keeps rollback practical.
