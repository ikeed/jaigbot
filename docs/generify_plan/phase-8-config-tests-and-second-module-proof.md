# Phase 8: Config, Tests, And Second-Module Proof

## Goal

Finish the modularization by cleaning up lingering AIMS-first config and test
assumptions and proving the architecture with a second thin module.

At the end of Phase 8:

- config/branding assumptions are module-aware
- core tests use neutral fixtures
- AIMS tests are module-local
- a second stub module can be selected end to end without editing core files

## Why This Phase Matters

Without a second-module proof, the architecture can still be accidentally
AIMS-shaped even if the code looks modular.

## Out Of Scope

- building a full production interview or HR module
- removing all legacy compatibility reads immediately

## Step-By-Step Plan

### Step 1: Clean config and branding assumptions

Review:

- env vars
- app title/default labels
- bucket/prefix defaults
- template labels
- diagnostics/config outputs

Move what should be module-owned out of core defaults where practical.

### Step 2: Reorganize tests by ownership

Core tests should verify:

- registry
- generic orchestration
- generic session/resume behaviors
- generic storage shell
- generic frontend shell/event logic

Module tests should verify:

- AIMS turn behavior
- AIMS startup/resume behavior
- AIMS summaries and analytics

### Step 3: Add a second stub module

Implement a thin non-AIMS module with just enough behavior to prove:

- registration works
- selection works
- dispatch works
- startup/resume/payload seams are truly generic

It does not need to be feature-rich.

### Step 4: Run architecture-focused regression checks

Explicitly test for things that often remain hidden:

- role counting still works for non-AIMS role names
- frontend shell does not assume AIMS event names
- summary capability can be absent cleanly
- module mismatch on resume is handled safely

### Step 5: Decide what compatibility shims can be retired

Only after the second-module proof should you decide whether some legacy AIMS
aliases or core-side compatibility paths can be removed.

## Foreseen Problems And Mitigations

### Problem 1: Core tests keep using AIMS-shaped fixtures

Mitigation:

- add neutral fixture sets deliberately
- review fixture naming and payload content, not just test locations

### Problem 2: Second-module proof is too thin to reveal coupling

Mitigation:

- make the stub differ from AIMS in at least:
  - role names
  - startup artifact shape
  - summary capability or lack of it

### Problem 3: Config cleanup breaks operations expectations

Mitigation:

- preserve aliases and defaults until rollout is ready
- document operational migrations explicitly

## Acceptance Criteria

1. core tests are not covertly AIMS-shaped
2. a second stub module works without core edits
3. remaining config/branding assumptions are deliberate rather than accidental
4. the platform is demonstrably extensible
