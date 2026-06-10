# Phase 2: Generic Envelope And Schema Decoupling

## Goal

Create the generic request/response seam that lets core transport speak in
module-neutral terms while preserving current AIMS-compatible API behavior.

At the end of Phase 2:

- core has a generic response envelope or equivalent transport wrapper
- AIMS-specific payloads can be carried through that envelope
- the codebase has a clean place for module-produced artifacts/feedback/summary
  data
- existing clients still receive the fields they depend on
- chat dispatch still does not depend on the registry yet

## Actual Starting Point After Phase 1

The repo already has:

- `TrainingModule` protocol
- `ModuleManifest` / `DialogueRoles` / branding metadata
- explicit built-in registry construction
- `ACTIVE_MODULE`
- startup-time active-module resolution
- a metadata-first AIMS adapter in `app/modules/aims/module.py`

What it does not yet have:

- a generic transport envelope
- compatibility serializers
- module-owned turn behavior

## Out Of Scope

Do not do any of the following in Phase 2:

- switch `ChatOrchestrator` to module dispatch
- migrate Redis or archive storage formats
- relocate AIMS runtime files
- modularize frontend loading
- remove old API aliases

## Why This Phase Exists

If Phase 3 routes chat through modules before there is a generic response seam,
the dispatch layer will just reproduce current AIMS-shaped payload logic under
new names.

Phase 2 exists to prevent that mistake.

## Actual Implementation Notes

Phase 2 landed with the following concrete seams:

- `ModuleResponseEnvelope` and `ModuleCompletion` in
  `app/core/response_types.py`
- compatibility serialization in `app/core/response_serialization.py`
- additive request-side extension points via `ChatRequest.moduleId` and
  `ChatRequest.moduleOptions`
- AIMS response shaping implemented in `AimsTrainingModule.format_module_response(...)`
- `ChatOrchestrator` now delegates response payload construction through the
  active module instead of assembling AIMS-shaped payloads inline

This means Phase 3 does not need to solve response serialization again. It
needs to switch execution dispatch to the module path while keeping this
serializer boundary intact.

## Step-By-Step Plan

### Step 1: Inventory the current request/response shapes

Review:

- `app/models.py`
- `app/services/chat_orchestrator.py`
- `app/services/aims_coaching_handler.py`
- `app/services/legacy_chat_handler.py`
- affected routes and frontend consumers

Catalog:

- required client-visible fields
- AIMS-only fields
- backward-compatibility aliases
- fields that are really transport metadata rather than domain payload

Split them conceptually into:

- transport envelope
- module payload
- compatibility aliases

### Step 2: Define generic transport-layer types

Add core-neutral types for:

- module response envelope
- module artifacts
- module feedback/evaluation payload
- completion/session metadata

Recommended top-level envelope fields:

- `reply`
- `session`
- `module`
- `artifacts`
- `feedback`
- `summary`
- `events`
- `transport_metadata`

Do not hardcode:

- `coach`
- `coaching`
- `coachPost`
- AIMS turn metrics

Those can remain as compatibility aliases layered on top.

### Step 3: Add a compatibility serializer layer

Do not force existing handlers or clients to switch all at once.

Create a serializer/adapter that can:

- accept a generic envelope
- emit current AIMS-compatible response fields while migration is in progress

This is the key Phase 2 mechanism.

It should be possible for AIMS to produce:

- generic envelope data

and then have core still emit:

- `reply`
- `coaching`
- `coachPost`
- old aliases like `text`, `modelId`, `latency_ms`

without teaching core that every module has coaching semantics.

### Step 4: Decide where request-level module options live

Current requests contain AIMS-shaped flags and assumptions.

Phase 2 should introduce a neutral place for module-directed behavior, such as:

- module options
- module context
- module request metadata

Do not yet require clients to send a `module_id` per request if deployment
config still chooses the active module, but design the request side so that a
future explicit module override has a home.

### Step 5: Introduce module-owned response shaping for AIMS

The AIMS adapter should gain enough behavior to expose:

- generic feedback payload
- generic artifact payload
- generic summary payload when present

But the current AIMS runtime implementation does not need to move.

Use a thin response-mapping layer around current handler results.

Important constraint:

- do not bypass the Phase 1 adapter by creating an unrelated response wrapper
  elsewhere
- extend `AimsTrainingModule` or clearly adjacent module-owned code so later
  dispatch work has one obvious place to attach behavior

### Step 6: Keep frontend compatibility stable

Before Phase 3, the frontend should still see the current response shape.

That means:

- generic envelope may exist internally
- compatibility fields still exist externally

Do not make frontend consumers switch to generic names in Phase 2.

### Step 7: Add tests for schema compatibility

Add tests that prove:

- generic envelope can represent AIMS responses
- compatibility serializer preserves old client-visible fields
- optional module payload sections are omitted cleanly when unsupported
- no AIMS-only assumptions leak into the core envelope schema

## Foreseen Problems And Mitigations

### Problem 1: The generic envelope becomes just a renamed AIMS payload

Mitigation:

- separate transport metadata from module payload
- explicitly test a hypothetical non-AIMS payload shape, even if only through a
  stub module

### Problem 2: Compatibility aliases leak back into core semantics

Mitigation:

- treat aliases as serializer concerns only
- keep core logic written against the generic envelope

### Problem 3: The request model remains permanently AIMS-shaped

Mitigation:

- add a neutral home for module options now
- avoid introducing more AIMS-specific request flags during this phase

### Problem 4: Frontend and API drift apart mid-migration

Mitigation:

- preserve current outward response shape until after Phase 3 is stable
- move one layer at a time: internal envelope first, client migration later

### Problem 5: Summary and artifact payloads are underspecified

Mitigation:

- define them structurally in the envelope now
- allow module-owned payload schemas inside them
- do not force core to interpret module semantics

### Problem 6: Phase 2 duplicates metadata already established in Phase 1

Mitigation:

- reuse Phase 1 manifest/module metadata rather than inventing parallel module
  descriptors for transport

## Acceptance Criteria

Phase 2 is complete only when:

1. there is a generic module response envelope in core
2. AIMS responses can be represented through that envelope
3. current clients still receive their expected fields through compatibility
   serialization
4. old AIMS field names are no longer the primary internal transport model
5. no chat dispatch path has been switched to the module registry yet

## Verification

Minimum verification:

```bash
git diff --check
.venv/bin/python -m compileall -q app tests
.venv/bin/python -m pytest -q tests/core tests/modules/aims
```

Plus targeted API/orchestrator tests covering:

- AIMS coaching response shape
- legacy response shape if still supported
- compatibility alias behavior
