# Phase 3: Orchestrator Dispatch

## Goal

Switch core control flow so the active module is resolved through the registry
and chat behavior is delegated through module-owned handlers.

At the end of Phase 3:

- `ChatOrchestrator` resolves the active module explicitly
- core delegates turn handling through the module contract
- AIMS runs through the module path rather than a hardcoded AIMS branch
- current user-visible behavior remains equivalent

## Actual Starting Point Expected From Earlier Phases

Before starting Phase 3, the repo should already have:

- explicit active-module resolution from Phase 1
- a generic response envelope and compatibility serializer from Phase 2
- an AIMS adapter that is ready to gain behavior, not just metadata
- response formatting already routed through `active_module.format_module_response(...)`
- temporary constructor-level registry fallback in `ChatOrchestrator` for
  non-app-state call paths

## Out Of Scope

Do not do any of the following in Phase 3:

- migrate Redis prefixes
- migrate archive schemas
- split frontend shell/module bundles
- move AIMS runtime files into final module directories
- remove old API aliases
- rewrite Chainlit startup/resume around module manifests yet

## Why This Phase Exists

This is the phase where the architecture stops being documentation and becomes
runtime truth.

It must come after Phase 2 because dispatch should target generic module
responses, not today's AIMS-shaped result dictionaries.

## Actual Implementation Notes

Phase 3 landed with the following concrete seams:

- `ChatOrchestrator` now routes chat turns through `_handle_module_turn(...)`
- `AimsTrainingModule.handle_turn(...)` owns the coaching-vs-legacy decision
  and delegates to the existing `AimsCoachingHandler` / `LegacyChatHandler`
- module-owned archive shaping now exists via `build_archive_payload(...)`
- response compatibility shaping still stays in
  `format_module_response(...)`

Two transitional compromises remain intentionally:

- direct `ChatOrchestrator` construction still has a defensive
  registry/settings fallback
- legacy chat behavior is wrapped inside the AIMS module rather than modeled
  as its own compatibility module yet

## Step-By-Step Plan

### Step 1: Introduce a module-facing orchestration seam

Refactor `ChatOrchestrator` so that:

- request validation stays in core
- session/context building stays in core
- active-module resolution becomes explicit
- turn execution is delegated to the active module
- response serialization stays in core

This means the orchestrator owns:

- transport
- validation
- context construction
- error normalization
- response serialization

The module owns:

- domain turn behavior
- module-specific prompt strategy
- module-specific feedback/artifacts

### Step 2: Create an AIMS module execution adapter

Before fully replacing branches, build a module-facing adapter around the
current AIMS path.

This adapter should call current AIMS services rather than reimplement them.

The point is to make:

- `AimsTrainingModule.handle_turn(...)`

delegate to current logic, not replace it.

If Phase 2 extended the AIMS adapter cleanly, this step should be an
incremental extension of that existing adapter rather than a new parallel
abstraction.

### Step 3: Define resolution rules explicitly

For Phase 3, active module resolution should still come from configured active
module, not from session memory or request overrides.

But the orchestrator code should be structured so that later phases can supply:

- session-stored `module_id`
- thread-stored `module_id`
- request-level override policies

without rewriting dispatch again.

Specific Phase 2 handoff concern:

- `app.main` already injects the resolved active module into
  `ChatOrchestrator`
- `ChatOrchestrator.__init__` still contains a defensive registry/settings
  fallback

Phase 3 should avoid creating a third resolution path. Consolidate around one
authoritative resolver story and keep any fallback clearly transitional.

### Step 4: Replace hardcoded AIMS branching in `ChatOrchestrator`

The current branching between:

- AIMS coaching path
- legacy path

should become:

- resolve active module
- call module turn handler
- serialize generic envelope to current outward API shape

If legacy behavior remains a supported mode, it should either:

- become its own module
- or be wrapped as a special compatibility module

Do not leave permanent hardcoded “module or legacy” branches in core.

### Step 5: Keep error boundaries explicit

Core should continue to own:

- request validation failures
- transport-level exceptions
- response-shape normalization

Modules should own:

- domain exceptions
- domain fallback behavior
- module-produced error context

Decide how module exceptions are normalized into transport-safe responses
before cutting over dispatch.

### Step 6: Preserve current response semantics through the serializer

Even after dispatch changes, current client-visible behavior should remain
stable because Phase 2 already created compatibility serialization.

That means:

- modules return generic envelopes
- core serializer emits current AIMS-compatible outward fields

The orchestrator should not reintroduce AIMS-specific alias logic inline.
Serializer ownership should stay where Phase 2 established it.

### Step 7: Add logging and diagnostics around module dispatch

At a minimum log:

- resolved `module_id`
- resolved module display name
- dispatch path taken
- serializer path taken

This is necessary because Phase 3 changes runtime control flow.

### Step 8: Add focused dispatch tests

Tests should cover:

- active module resolution feeding the orchestrator
- AIMS dispatch through the module path
- preserved outward response shape
- unknown module resolution failure behavior
- module-thrown exception normalization

## Foreseen Problems And Mitigations

### Problem 1: Dispatch is switched before AIMS adapter is truly thin

If the AIMS module starts re-owning too much logic here, file relocation later
gets harder.

Mitigation:

- keep the adapter delegating to current services
- do not fold relocation into Phase 3

### Problem 2: The old legacy path remains hardcoded forever

Mitigation:

- require a decision during Phase 3:
  - either wrap legacy mode as a module
  - or explicitly deprecate it

Do not leave a permanent architectural escape hatch in core.

### Problem 3: Error behavior changes subtly

Mitigation:

- snapshot or regression-test the main response/error cases before cutover
- keep transport-level normalization in core

### Problem 4: Module dispatch starts depending on future resume/storage state

Mitigation:

- keep Phase 3 resolution config-driven only
- structure the resolver for future session/thread sources without requiring
  them yet

### Problem 5: Core still assembles domain prompts

Mitigation:

- during dispatch cutover, ensure prompt construction is invoked through the
  module-facing path
- do not leave a permanent core assumption about `character` and `scene`

### Problem 6: Registry resolution spreads across multiple runtime surfaces

Mitigation:

- keep one resolver path for active-module selection
- do not let `ChatOrchestrator`, routes, and helper functions each invent
  their own fallback rules

### Problem 7: Phase 3 accidentally reimplements response formatting inside dispatch

Mitigation:

- preserve `format_module_response(...)` as the only response-shaping seam
- let `handle_turn(...)` return a module-neutral result or envelope
- do not move compatibility alias logic back into `ChatOrchestrator`

## Acceptance Criteria

Phase 3 is complete only when:

1. `ChatOrchestrator` dispatches through the active module
2. AIMS behavior runs through the module pathway without user-visible
   regression
3. outward API compatibility is preserved through serializer/adapters
4. the hardcoded AIMS branch is removed from core orchestration
5. dispatch logging and tests make failures diagnosable

## Verification

Minimum verification:

```bash
git diff --check
.venv/bin/python -m compileall -q app tests
.venv/bin/python -m pytest -q tests/core tests/modules/aims
```

Then targeted existing tests covering:

- chat orchestrator behavior
- AIMS coaching path behavior
- relevant API route tests
- error normalization behavior
