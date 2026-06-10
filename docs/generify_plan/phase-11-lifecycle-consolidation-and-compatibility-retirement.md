# Phase 11: Lifecycle Consolidation And Compatibility Retirement

## Objective

Consolidate lifecycle ownership now that the modular seams are proven, then
retire the most dangerous compatibility scaffolding deliberately.

This phase is where the architecture stops pretending to be provisional.

## Why This Phase Exists

The repo now has working modular seams, but some implementation shortcuts were
kept intentionally:

- fresh built-in registries are rebuilt in several code paths
- active-module resolution still has defensive fallback behavior
- missing archive `module_id` still falls back to the deployment's active
  module
- old import-path compatibility shims still exist
- legacy chat remains embedded inside the AIMS module rather than represented
  as an explicit compatibility runtime

These were the right tradeoffs earlier. They should not become permanent.

Phase 11 assumes Phase 9 and Phase 10 already landed. In particular:

- bootstrap transport should already have a generic first-class shape
- frontend presentation should already consume module-owned role/branding seams

That lets this phase focus on lifecycle and compatibility removal instead of
reopening transport or shell-identity design.

## Scope

### In Scope

- registry and active-module lifecycle consolidation
- compatibility shim retirement plan
- legacy archive/bootstrap adapter strategy
- final cleanup of redundant resolution/fallback code

### Out Of Scope

- broad new module feature work
- visual redesign

## Problems To Solve

### 1. Registry Rebuilds In Request Paths

Current examples:

- `app/main.py`
- `app/services/chat_orchestrator.py`
- `app/services/chainlit/orchestrator.py`
- `app/services/storage_service.py`

This is fine while modules are stateless. It is not the lifecycle we want once
modules own more collaborators.

### 2. Active-Module Resolution Still Has Transitional Fallbacks

This is useful for tests and direct construction, but it should converge onto a
clear authoritative path.

### 3. Legacy Data Without `module_id` Still Depends On Deployment Defaults

That is acceptable for the current deployment model, but not for:

- mixed-module buckets
- cross-deployment readers
- future migration tooling

### 4. Import-Path Compatibility Shims Still Obscure Real Ownership

They reduced risk during the move, but they also hide which paths are meant to
be stable now.

## Implementation Plan

1. Establish the authoritative registry lifecycle.
   - registry created once at app startup
   - dependencies read from app state or explicit injection
   - tests updated to use the same path

2. Remove redundant constructor/runtime fallbacks where safe.
   - `ChatOrchestrator`
   - `ChainlitOrchestrator`
   - any other module-resolving helpers

3. Design explicit legacy archive/bootstrap adapters.
   - distinguish:
     - no `module_id` because legacy AIMS archive
     - malformed archive
     - unknown future module
   - do not silently map everything to the active deployment module forever

4. Retire compatibility shims in controlled batches.
   - remove one ownership family at a time
   - update imports and tests first
   - keep rollback simple

5. Revisit whether legacy chat should remain a hidden path inside the AIMS
   module or become an explicit compatibility module/runtime mode.

6. Update docs again.
   - note which compatibility layers were removed
   - update contributor guidance and ownership maps

## Risks

### Risk 1: Breaking Tests Or Tooling That Bypass Lifespan

Mitigation:

- convert tests onto authoritative dependency paths before removing fallbacks
- keep explicit test helpers rather than hidden production fallbacks

### Risk 2: Mishandling Legacy Archives

Mitigation:

- add explicit fixtures for old archive shapes
- treat archive adaptation as versioned compatibility work, not opportunistic
  inference

### Risk 3: Removing Shims Too Early

Mitigation:

- audit downstream imports first
- remove shims in small batches with clear ownership boundaries

## Verification

- targeted unit tests for dependency resolution and archive adaptation
- full non-integration suite
- any migration fixtures or archive-read tests added for legacy payloads

## Done Means

- one authoritative registry/module lifecycle exists
- redundant active-module fallbacks are gone or clearly limited to test helpers
- legacy archive/bootstrap handling is explicit rather than deployment-default
  magic
- compatibility shims are meaningfully reduced or fully retired where safe
