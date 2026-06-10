# Phase 10: Branding And Presentation Cleanup

## Objective

Make the shared shell present itself as a generic training platform instead of
an AIMS-only product, while keeping module-specific branding owned by the
active module.

This phase is about identity and presentation, not core dispatch semantics.

## Why This Phase Exists

After Phase 8 and the planned Phase 9 work, the backend/runtime seams are
largely modular. What remains obviously AIMS-specific is the shell itself:

- `APP_TITLE`
- login and duplicate-tab templates
- some avatar titles and labels
- documentation that still frames the codebase as single-module by default
- CSS ownership that is only partly module-aware

Phase 9 should be treated as an input here, not re-litigated. By the time this
phase begins, the backend should already expose:

- module-defined role labels
- generic bootstrap artifact lists
- generic bootstrap participant/state blocks

Phase 10 should consume those seams rather than invent new parallel ones.

If left alone, those surfaces will keep pulling future work back toward the
assumption that AIMS is the one true app.

## Scope

### In Scope

- deployment-shell branding
- module-aware presentation metadata consumption
- CSS/theming ownership strategy
- documentation and agent guidance updates needed to reflect the modular app

### Out Of Scope

- registry lifecycle consolidation
- archive compatibility retirement
- import-path shim removal

## Problems To Solve

### 1. Core Branding Still Says AIMSBot

Current examples:

- `app/constants.py`
- templates served by the FastAPI shell
- some docs and asset names

### 2. CSS Ownership Is Still Deployment-Level

Current example:

- one Chainlit `custom_css` entrypoint

JS is now manifest-driven, but CSS still behaves like one global theme.

### 3. Documentation And Agent Guidance Lag Behind The Code

Important examples:

- `AGENTS.md`
- developer setup docs
- architecture docs
- UI docs

These files now need to explain:

- core vs module ownership
- active module selection
- second built-in module existence
- which areas are intentionally still AIMS-first

## Implementation Plan

1. Decide shell identity.
   - Pick a neutral platform-facing name for core surfaces.
   - Keep module display names coming from manifest branding.

2. Replace hardcoded shell branding in code and templates.
   - `APP_TITLE`
   - login page copy
   - duplicate-tab page copy
   - any other shell-level text or template titles

3. Decide CSS ownership strategy.
   - Either:
     - one shell stylesheet with module sections
     - or manifest-driven CSS with explicit module loading
   - Make the strategy explicit and document it.

4. Align frontend presentation with active-module branding.
   - loading text
   - avatar labels where appropriate
   - neutral fallback strings when a module omits branding fields
   - role labels and startup-artifact handling should come from the Phase 9
     seams rather than AIMS-first heuristics

5. Update documentation.
   - `AGENTS.md`
   - setup docs
   - architectural docs
   - module development guidance

6. Audit docs for misleading single-module assumptions.
   - specifically call out where AIMS remains the primary shipped experience
   - do not overstate generic completeness

## Risks

### Risk 1: Branding Cleanup Becomes A Product Redesign

Mitigation:

- keep the task operational
- rename and reframe only the shared shell
- leave module-specific UI personality to modules

### Risk 2: CSS Loading Changes Break Existing Dialog Or Chat Styling

Mitigation:

- choose one ownership strategy and test it in the browser
- prefer additive module theming over broad stylesheet churn

### Risk 3: Docs Drift Faster Than Code

Mitigation:

- update `AGENTS.md` and the key developer docs in the same phase
- explicitly note any known remaining AIMS-specific areas instead of pretending
  they are already generic

## Verification

- browser check on login, duplicate-tab, startup, and module loading flows
- focused route/template checks if applicable
- docs review for coherence with actual code layout

## Done Means

- core shell branding is neutral
- active module branding drives user-facing identity where appropriate
- CSS ownership is an explicit, documented system
- `AGENTS.md` and core docs describe the modular architecture accurately
