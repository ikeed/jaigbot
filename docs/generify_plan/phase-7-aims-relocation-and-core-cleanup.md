# Phase 7: AIMS Relocation And Core Cleanup

## Goal

Move AIMS implementation physically behind module-owned boundaries and remove
residual AIMS-specific imports and assumptions from core.

At the end of Phase 7:

- AIMS implementation files that benefit from relocation live under
  `app/modules/aims/` or clearly module-owned paths
- core no longer imports AIMS services directly
- shared utilities that remain in core are genuinely generic

## Why This Phase Comes Late

Physical relocation should be the result of proven runtime seams, not the
mechanism for creating them. Doing it earlier makes every later phase noisier
and harder to verify.

## Out Of Scope

- major prompt redesign
- new product behavior
- second-module proof work beyond what is needed for cleanup confidence

## Step-By-Step Plan

## Actual Starting Point After Phase 6

The repo already has:

- module-owned turn dispatch
- module-owned session bootstrap
- module-owned summary routing
- module-owned archive-envelope shaping
- a generic frontend bootstrap loader
- manifest-driven module JS bundles
- generic lifecycle/event names in core frontend/backend code

Implication:

- Phase 7 should move the remaining AIMS implementation behind the module
  boundary that already exists instead of trying to invent new seams during the
  file moves
- frontend relocation is now part of the ownership cleanup as well, especially
  for AIMS-owned JS that still sits under the shared shell paths

### Step 1: Classify files by true ownership

For each remaining AIMS-adjacent file, decide whether it is:

- truly core
- truly AIMS-specific
- split between the two and needs extraction

### Step 2: Move module-owned files incrementally

Relocate:

- AIMS engine and prompts
- generic-named AIMS services that already sit behind proven module seams
- AIMS prompts
- AIMS summary/analytics logic

Do not batch everything into one giant rename if smaller moves preserve sanity.
Leave the larger AIMS-prefixed orchestration/state cluster in place if moving it
would mostly create diff noise and coverage drag.

### Step 3: Remove residual core imports

Core should stop importing:

- AIMS services
- AIMS prompts
- AIMS-only helper functions

### Step 4: Re-home split helpers

Some helpers will need to be:

- kept in core if truly generic
- duplicated temporarily
- or moved into AIMS if they are actually domain-specific

Examples to watch for:

- prompt builders
- concern extraction helpers
- AIMS fallback copy

### Step 5: Clean dead compatibility shims

Only after runtime is proven should obviously obsolete direct AIMS hooks in
core be removed.

## Foreseen Problems And Mitigations

### Problem 1: Utility files look generic but are semantically AIMS-specific

Mitigation:

- judge by behavior ownership, not filename

### Problem 2: Relocation creates massive diff noise

Mitigation:

- move incrementally
- keep behavior changes separate from file moves where possible

### Problem 3: Coverage drops because moved files were previously under-tested

Mitigation:

- move the best-covered AIMS-owned files first
- add focused regression tests for any file whose coverage would otherwise fall
  below the project bar
- defer low-value moves of large AIMS-prefixed service clusters until a later
  phase actually needs them

## Acceptance Criteria

1. AIMS engine, prompts, and module-owned generic-named services are
   physically module-owned
2. core no longer imports moved AIMS implementation directly
3. remaining shared helpers are demonstrably generic or explicitly deferred
4. runtime behavior remains unchanged
