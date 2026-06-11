# Phase 16: Branding, Assets, And Documentation Finish Pass

## Status

Implemented.

## Objective

Finish the non-runtime cleanup so the repo and shell presentation stop leaking
old AIMSBot-era naming where it is no longer useful.

## Why This Phase Exists

The runtime seams are now much cleaner than the presentation layer:

- shared asset names still use `aimsbot`
- some avatar and JS/CSS names are still AIMS-era
- historical docs still carry more transition narrative than a stable platform
  repo should eventually keep in the main guides

## Scope

### In Scope

- shared static asset/file naming cleanup
- broader docs cleanup, including another `AGENTS.md` pass if needed
- clarifying which historical docs remain intentionally historical

### Out Of Scope

- new runtime modularization work
- archive/schema changes

## Problems To Solve

### 1. Shared Asset Names Still Leak AIMS

Examples included the old shared shell logo path and AIMS-era avatar or bundle
names that were used by the generic shell.

### 2. Documentation Still Carries Too Much Transition History

Some historical plan docs are useful. Some general docs should become cleaner
once the runtime and ownership work stabilizes.

### 3. Contributor Guidance Should Match The Final Layout

`AGENTS.md` should be revisited one more time after runtime cleanup phases
finish so new contributors are steered toward stable paths only.

## Implementation Plan

1. Inventory shared assets and decide which renames are worth the churn.
2. Update shell references and module manifests as needed.
3. Review docs for:
   - stale AIMS-only assumptions in generic guides
   - transition notes that should move to historical docs
4. Do one final contributor-guidance pass in `AGENTS.md`.

## Verification

- targeted UI smoke checks for renamed assets
- `git diff --check`
- full non-integration suite if asset or route references move

## What Landed

- renamed shared shell assets and loader paths to generic names:
  - `public/training-ui.js`
  - `public/training-ui.css`
  - `public/training-platform.png`
  - `public/js/platform/`
- updated live references in:
  - `.chainlit/config.toml`
  - module manifests
  - UI routes
  - frontend tests
- refreshed shared avatar `<title>` metadata so shell-owned assets no longer
  read as AIMSBot-specific
- updated the planning/docs set so current shell references point at the new
  generic paths

## Residual Issues

- AIMS-specific product docs remain intentionally AIMS-specific where they
  describe the shipped AIMS module rather than the generic shell
