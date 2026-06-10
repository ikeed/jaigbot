# Phase 12: Frontend Role And Artifact Presentation

## Objective

Finish the browser-shell side of the modular seams introduced in Phases 9-11.

At the end of this phase, the backend should no longer be the only place that
understands:

- module-defined role labels
- module startup artifacts
- module-owned shell presentation hints

## Why This Phase Exists

The backend now carries richer generic structure:

- `dialogue_roles.display_names`
- generic bootstrap `module.artifacts`
- generic bootstrap `module.participantContext`

But the browser shell still behaves as if:

- one AIMS-flavored message family is always visible
- the first startup artifact is the only artifact that matters
- one deployment-level stylesheet is enough forever

That gap is now the biggest remaining obstacle to adding richer non-AIMS
modules without bending the frontend back into AIMS assumptions.

## Scope

### In Scope

- visible author/role label presentation from module metadata
- explicit startup-artifact rendering strategy
- module-owned shell presentation decisions
- browser verification of the updated `/chat` flow

### Out Of Scope

- major visual redesign
- new domain logic for AIMS or interview behavior

## Problems To Solve

### 1. Role Labels Stop At The API Boundary

The backend understands module role labels, but the browser shell still renders
messages with one AIMS-first presentation model.

### 2. Startup Artifacts Are Still Effectively Single-Slot

`module.artifacts` is plural, but the shell still mainly treats the first
artifact as the only meaningful startup surface.

### 3. CSS Ownership Is Still Unsettled

`frontendCss` is exposed in manifests and `/config`, but the actual browser
shell still loads one deployment-level stylesheet entrypoint.

## Implementation Plan

1. Audit the current frontend message-rendering path.
   - identify where author labels and avatars are assigned
   - identify where `availableModules` and `dialogueRoles` from `/config` can
     be consumed safely

2. Add a shell-level role-label model.
   - define how the browser obtains display names for:
     - participant roles
     - feedback roles
     - metadata roles
   - ensure default fallbacks remain sane for old sessions

3. Replace implicit first-artifact behavior with an explicit artifact strategy.
   - define which artifact kinds are:
     - primary modal surfaces
     - secondary inline cards
     - passive metadata
   - make the browser behavior depend on artifact kind, not array position

4. Decide and implement the stylesheet strategy explicitly.
   - either:
     - keep one shell stylesheet with module sections, documented clearly
   - or:
     - load module-specific stylesheets from the manifest
   - do not leave the current half-state ambiguous

5. Update tests and browser verification.
   - unit tests for frontend message/artifact handling where possible
   - real browser sanity check for:
     - AIMS startup
     - interview startup
     - resume/duplicate paths

## Risks

### Risk 1: Frontend State Drift From Backend Contracts

Mitigation:

- consume `/config` and bootstrap payloads directly rather than duplicating
  role/branding tables in JS

### Risk 2: Artifact Kinds Become Another Ad Hoc Taxonomy

Mitigation:

- keep the artifact-kind vocabulary narrow and documented
- prefer module-owned metadata over frontend-only special cases

### Risk 3: Style Loading Becomes Order-Dependent

Mitigation:

- if multiple stylesheets are allowed, document and test load order
- otherwise explicitly keep one shell stylesheet and stop pretending it is
  module-driven today

## Verification

- targeted unit tests for frontend helpers
- browser-based verification of local `/chat` flows
- full non-integration suite if backend-facing message/bootstrap contracts move

## Done Means

- frontend message labels follow module metadata
- startup artifact handling is explicit and no longer “first artifact wins”
- stylesheet ownership is an explicit architectural choice, not an accidental
  hybrid
