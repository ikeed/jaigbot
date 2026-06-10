# Phase 6: Frontend Shell Modularization

## Goal

Separate the generic frontend shell from AIMS-specific UI behavior and standardize
the window-message/event vocabulary around module-neutral lifecycle concepts.

At the end of Phase 6:

- the generic UI shell can run without AIMS-specific UI logic loaded
- AIMS-specific UI behavior is loaded through module metadata
- core JS event names are module-neutral
- Chainlit still uses one stable bootstrap entrypoint

## Why This Phase Comes After Phase 5

Frontend modularization depends on stable module manifests and runtime payload
shapes. Doing it earlier would create duplicated migration work and brittle
message translations.

## Out Of Scope

- replacing Chainlit
- visual redesign
- physical relocation of every AIMS frontend asset in one shot if wrappers are sufficient

## Actual Starting Point After Phase 5

The repo already has:

- module-owned session bootstrap on the backend
- module-aware current-thread and resume validation
- module-owned summary routing
- module-aware archive/session payloads with generic `module` metadata
- compatibility-shaped frontend bootstrap fields such as `initialCard` and
  `personaName`

Implication:

- Phase 6 should treat the remaining AIMS-specific startup UI as a frontend
  vocabulary and asset-ownership problem, not as a backend bootstrap,
  persistence, or summary problem

## Step-By-Step Plan

### Step 1: Inventory shell vs AIMS-specific frontend behavior

Classify existing frontend code into:

- generic shell plumbing
- session controls
- duplicate-tab handling
- generic modal infrastructure
- AIMS intro flow
- AIMS infographic behavior
- AIMS-specific labels and visuals

### Step 2: Freeze a generic UI event vocabulary

Define core-neutral events such as:

- `training_start`
- `training_resume`
- `training_feedback`
- `training_artifact`
- `participant_name`

Allow modules to emit namespaced extras if needed, but the shell should not
depend on AIMS names.

### Step 3: Keep one Chainlit bootstrap loader

Do not try to make `.chainlit/config.toml` vary per module.

Use:

- one generic bootstrap JS entrypoint
- one generic CSS entrypoint if needed

That bootstrap should consult the active-module manifest and load module-owned
assets deterministically.

### Step 4: Split the shell gradually

Move or wrap:

- generic shell logic into platform-owned frontend files
- AIMS-specific logic into module-owned frontend files

This can be done incrementally with compatibility shims if needed.

### Step 5: Remove AIMS-prefixed core event names

Core JS and core Python should stop emitting/depending on:

- `aims_*` event names

Module-specific code may still translate legacy names temporarily during the
migration window.

### Step 6: Keep runtime behavior stable during the split

This phase should not change:

- intro behavior
- duplicate-tab behavior
- scenario/briefing rendering behavior

except where namespacing and ownership need to move.

## Foreseen Problems And Mitigations

### Problem 1: Chainlit loader complexity explodes

Mitigation:

- one bootstrap loader only
- deterministic manifest-driven asset loading

### Problem 2: Core and module events drift

Mitigation:

- define and document the generic event vocabulary before moving code

### Problem 3: AIMS branding remains scattered in templates and CSS

Mitigation:

- track branding migration separately
- use manifest-owned branding metadata consistently

## Acceptance Criteria

1. generic shell can load without importing AIMS-specific UI code
2. AIMS UI behavior is manifest/module owned
3. core event vocabulary is module-neutral
4. Chainlit bootstrap remains deterministic and maintainable
