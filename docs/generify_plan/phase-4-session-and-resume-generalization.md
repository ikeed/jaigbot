# Phase 4: Session And Resume Generalization

## Goal

Make session bootstrap, history shaping, current-thread handling, and resume
recovery module-aware without yet migrating storage key formats or archive
schemas.

At the end of Phase 4:

- startup/session bootstrap runs through module-owned seams
- resume logic validates and recovers sessions with module awareness
- core no longer assumes every module is persona/scenario based
- history trimming and role counting no longer hardcode AIMS dialogue roles

## Why This Phase Comes After Phase 3

Before chat dispatch goes through the module layer, there is no stable place
for a module to own session semantics. Once Phase 3 is complete, the same
adapter that owns turn handling can start owning startup/resume semantics.

## Out Of Scope

- migrating Redis key prefixes
- changing archive schema
- frontend asset-bundle splitting
- relocating AIMS files

## Actual Starting Point After Phase 1

The repo already has:

- `ACTIVE_MODULE`
- startup-time active-module resolution
- `resume_validation(...)` on the module contract
- `dialogue_roles(...)` metadata

But runtime still has AIMS-shaped assumptions in places like:

- `app/services/session_initializer.py`
- `app/services/session_service.py`
- `app/services/chat_helpers.py`
- `app/chainlit_thread_state.py`
- `app/services/chainlit/orchestrator.py`

## Step-By-Step Plan

### Step 1: Inventory runtime session assumptions

Identify every place core currently assumes:

- persona/scenario startup
- current thread always belongs to AIMS
- user/assistant are the only counted dialogue roles
- startup artifacts are scenario cards
- resume failure should become fresh AIMS scenario flow

Primary files:

- `app/services/session_initializer.py`
- `app/services/session_service.py`
- `app/services/chat_helpers.py`
- `app/chainlit_thread_state.py`
- `app/services/chainlit/orchestrator.py`

### Step 2: Introduce generic session/bootstrap types

Add neutral types for:

- session bootstrap payload
- startup artifact
- module runtime state
- resume context

These should live in core, but the module should populate them.

Avoid long-term core fields like:

- `character`
- `scene`
- `persona`
- `scenario_card`

Those may remain temporarily as compatibility data, but should stop being the
core session model.

### Step 3: Make history role counting module-aware

Current history shaping and trimming still assumes AIMS role semantics.

Refactor core history utilities so they ask the active module which roles count
as dialogue roles.

Important files:

- `app/services/session_service.py`
- `app/services/chat_helpers.py`

Do not migrate stored history yet. Just stop hardcoding role semantics in core.

### Step 4: Move startup artifact selection behind the module

Core should own startup transport mechanics.

The module should own:

- whether there is an intro
- whether there is a scenario/briefing artifact
- whether there are module-specific startup documents or instructions

For AIMS, the initial implementation may still produce the existing scenario
card behavior, but the ownership should move.

### Step 5: Make current-thread and resume checks module-aware

Current-thread pointers and resume validation must consult:

- stored/persisted `module_id` when available
- active module
- module `resume_validation(...)`

Define explicit policies for:

- module mismatch
- stale thread with no recoverable state
- missing thread record
- missing backend history

Do not let core silently assume “fresh AIMS scenario” is always the right
fallback forever.

### Step 6: Keep fallback behavior explicit and testable

Core can still own safety behavior such as:

- do not crash on stale pointers
- do not resume another user’s thread

But modules should influence what “recover to fresh start” means.

### Step 7: Add focused tests

Test:

- dialogue-role counting through module metadata
- stale current-thread recovery with module-aware validation
- startup payloads no longer requiring AIMS scenario-card assumptions
- resume mismatch handling when stored module id differs

## Foreseen Problems And Mitigations

### Problem 1: Resume logic hardcodes AIMS fallback semantics

Mitigation:

- core should distinguish “resume failed safely” from “module wants fresh start”
- module decides the startup recovery payload

### Problem 2: Hidden history assumptions remain in helper functions

Mitigation:

- search shared helpers for `ROLE_USER`, `ROLE_ASSISTANT`, `ROLE_COACH`
- move domain-specific helpers out of shared core if needed

### Problem 3: Session payload shape becomes half-generic, half-AIMS forever

Mitigation:

- define the neutral session/bootstrap model early in this phase
- keep compatibility shims, but stop adding new AIMS-specific core fields

## Acceptance Criteria

1. session bootstrap is described in generic types
2. history trimming/counting depends on module dialogue-role metadata
3. resume validation consults module-aware rules
4. stale-thread handling no longer assumes AIMS-only semantics in core
5. current user-visible AIMS behavior remains equivalent

