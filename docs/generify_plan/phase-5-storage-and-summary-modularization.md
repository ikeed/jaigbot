# Phase 5: Storage And Summary Modularization

## Goal

Make session memory metadata, archive payloads, and summary generation
module-aware while preserving read compatibility for existing AIMS data.

At the end of Phase 5:

- new persistence paths can record `module_id`
- archive payloads can carry module-owned analytics/summary blocks
- summary generation routes through module-owned seams
- old AIMS archives and session shapes are still readable

## Why This Phase Comes After Phase 4

Storage migration should not start until runtime session/resume ownership is
clear. Otherwise the app will persist ambiguous state and force multiple
migrations.

## Out Of Scope

- frontend modular loading
- physical relocation of AIMS files
- removing old archive readers

## Step-By-Step Plan

### Step 1: Inventory persisted shapes precisely

Capture current shapes for:

- Redis/in-memory session records
- GCS session archives
- summary payloads
- session-related metadata copied into archives

### Step 2: Define the module-aware persistence envelope

Introduce core-neutral structures for:

- persisted session metadata
- archive module metadata
- module analytics payload
- module summary payload

At minimum, new writes must have room for:

- `module_id`
- schema version
- module payload version

### Step 3: Introduce versioned adapters

Do not put migration conditionals everywhere.

Create explicit adapter logic for:

- old AIMS archive/session shapes
- new module-aware shapes

The core storage layer should dispatch through adapters rather than accumulate
anonymous `if old field exists` logic.

### Step 4: Add module-owned archive and summary shaping

Core should own:

- writing/reading transport and storage shell
- generic archive envelope

The module should own:

- archive payload details
- analytics payload details
- summary payload details

### Step 5: Introduce `module_id` into runtime persistence safely

Once the envelope and adapters exist, begin storing `module_id` in:

- new session writes
- new archives
- new summaries

Do not yet force Redis key-prefix migration in the same change unless the
runtime is ready for it.

### Step 6: Prepare key-prefix migration separately

This is where many migrations go wrong.

Recommended approach:

- first make values module-aware
- then change key prefixes in a separate sub-phase with fallback reads

That lets behavior be validated before physical key namespace changes.

### Step 7: Generalize `/summary`

Make summary generation a module capability.

Core should be able to represent:

- module has a summary capability
- module does not have a summary capability

without assuming AIMS semantics.

## Foreseen Problems And Mitigations

### Problem 1: Archive migration and key migration get coupled

Mitigation:

- separate value-shape migration from key-prefix migration

### Problem 2: Old reports become unreadable

Mitigation:

- keep legacy adapters for read paths longer than old write paths

### Problem 3: Summary stays AIMS-shaped behind a generic wrapper

Mitigation:

- make summary payload module-owned
- keep core summary transport thin

## Acceptance Criteria

1. new persistence envelopes can carry `module_id`
2. core storage no longer needs to know AIMS analytics field names
3. summary generation is a module capability
4. old AIMS archives remain readable
5. key-prefix migration is prepared but not conflated with unrelated storage work

