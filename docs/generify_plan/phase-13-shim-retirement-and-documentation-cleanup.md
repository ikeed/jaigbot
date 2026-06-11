# Phase 13: Shim Retirement And Documentation Cleanup

## Status

Implemented.

## Objective

Retire the remaining import-path compatibility shims in deliberate batches and
finish the documentation cleanup once the browser shell is no longer
AIMS-first.

## Why This Phase Exists

The architecture now works through generic seams, but the repo still carries
old compatibility layers such as:

- `app/aims_engine.py`
- `app/prompts/aims.py`
- thin service re-export modules under `app/services/`

These were useful during the transition. Leaving them in place indefinitely
would keep the ownership model blurry for both runtime code and contributors.

The docs situation is similar:

- `AGENTS.md` and key platform docs now reflect the generic shell
- many repo paths and contributor habits still naturally point back to the old
  AIMS-only mental model

## Scope

### In Scope

- controlled shim retirement
- downstream import cleanup
- broader documentation updates, including `AGENTS.md`
- contributor ownership-map cleanup

### Out Of Scope

- new domain-module features
- major frontend redesign

## Problems To Solve

### 1. Compatibility Shims Still Hide Real Ownership

They make the repo look flatter than it really is and slow down future module
work because contributors keep reaching for the old paths.

### 2. Test Imports Still Depend On Transitional Paths

A broad shim deletion without staged import updates will create noisy failures
and unclear ownership changes.

### 3. Docs Still Mix “Generic Platform” And “AIMS App” Frames

That is tolerable while the UI is still partly AIMS-first. It becomes a real
problem once the browser shell is cleaned up.

## Implementation Plan

1. Inventory shim usage by family.
   - engine/prompt shims
   - generic-named service shims
   - AIMS-prefixed wrappers that are no longer needed

2. Retire one shim family at a time.
   - update app imports first
   - update tests second
   - remove the shim last

3. Add explicit migration notes where the new path is non-obvious.
   - especially for docs and contributor guidance

4. Do the broader documentation pass.
   - update `AGENTS.md`
   - update architecture/ownership docs
   - update setup/developer docs where paths or mental models changed

5. Re-run full verification after each removal batch.

## Risks

### Risk 1: Excessively Broad Import Churn

Mitigation:

- remove shims in batches, not all at once
- keep each batch ownership-focused

### Risk 2: Docs Get Ahead Of The UI Reality

Mitigation:

- do this only after Phase 12 lands
- keep AIMS-specific docs intentionally AIMS-specific where appropriate

### Risk 3: Losing Useful Legacy Wayfinding Too Early

Mitigation:

- keep migration notes in docs instead of leaving runtime shims forever

## Verification

- targeted tests for each removed import family
- full non-integration suite
- grep checks confirming shim references are gone where intended

## What Landed

- removed the remaining runtime shim files:
  - `app/aims_engine.py`
  - `app/prompts/aims.py`
  - the AIMS service re-export stubs under `app/services/`
- rewired remaining app imports to their owned module paths
- rewired unit, regression, and integration imports plus patch targets to the
  owned module paths
- updated contributor-facing docs:
  - `AGENTS.md`
  - `public/js/platform/README.md`
  - historical plan/cleanup docs now explicitly mark old path references as
    historical context

## Residual Issues

- several AIMS-owned runtime services still physically live under
  `app/services/` by design, which is now an ownership/relocation choice
  rather than a shim-compatibility issue
- some planning docs still intentionally mention pre-move paths as transition
  history; that is now documented instead of silently stale
