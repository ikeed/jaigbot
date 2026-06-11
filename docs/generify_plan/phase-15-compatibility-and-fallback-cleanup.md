# Phase 15: Compatibility And Fallback Cleanup

## Status

Implemented.

## Objective

Clean up the remaining runtime compatibility seams that are still acceptable
today but too loose for a stable multi-module platform.

## Why This Phase Exists

The platform is now structurally modular, but two runtime seams are still
intentionally transitional:

- direct construction falls back to the cached built-in active module when no
  explicit `active_module` is injected
- legacy module inference only knows how to recognize historical AIMS payloads

That is operationally safe today. It is not the long-term shape for a system
that wants strict ownership and clearer dependency flow.

## Scope

### In Scope

- tightening `active_module` injection and construction paths
- deciding the future of `LegacyChatHandler`
- clarifying or improving legacy module inference boundaries

### Out Of Scope

- branding or asset renaming
- broad documentation polish
- new training-module features

## Problems To Solve

### 1. Direct Construction Still Has A Transitional Fallback

Core services like `ChatOrchestrator` still tolerate `active_module=None` and
resolve the built-in active module internally.

That is convenient. It also weakens the dependency boundary.

### 2. Legacy Module Inference Is AIMS-Specific By Design

`app/core/legacy_module_resolution.py` knows how to detect historical AIMS
thread/archive families. That is fine for this repo today, but it should be
made explicitly bounded and documented rather than left half-generic.

### 3. The Legacy Non-Coaching Path Is Still Semantically Fuzzy

`LegacyChatHandler` is now owned by AIMS physically, but it still represents a
compatibility-oriented fallback path rather than a cleanly named module-owned
service family.

## Implementation Plan

1. Audit construction paths for core services and decide where `active_module`
   must become mandatory.
2. Reduce or remove implicit built-in runtime fallback where explicit
   injection is now feasible.
3. Decide whether `LegacyChatHandler` remains:
   - an AIMS-owned compatibility service
   - or becomes a more explicitly named AIMS fallback service
4. Review `legacy_module_resolution.py` and document its deliberate scope.
5. Update tests to reflect stricter construction expectations.

## Verification

- focused unit tests around construction and module resolution
- full non-integration suite

## What Landed

- `ChatOrchestrator` now requires an explicit `active_module` instead of
  silently resolving the built-in active module internally
- `ChainlitOrchestrator` now requires an explicit `active_module` as well
- the app-level chat-orchestrator factory now raises if it is called without an
  explicit active module, keeping the dependency boundary honest
- `legacy_module_resolution.py` now documents its deliberate scope clearly:
  legacy inference is intentionally narrow and AIMS-specific, and unknown
  legacy shapes must return `None`
- `LegacyChatHandler` was kept as an AIMS-owned compatibility path and its
  module/class documentation now says so directly
- the remaining UI redirect seam now uses the resolved app-state active module
  ID rather than `settings.ACTIVE_MODULE`

## Residual Issues

- `LegacyChatHandler` is still a compatibility-oriented AIMS path rather than a
  renamed fallback family with more explicit product semantics
