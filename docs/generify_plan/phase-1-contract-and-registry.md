# Phase 1: Contract And Registry

## Goal

Introduce the generic module contract and a static registry with no meaningful
runtime behavior change.

At the end of Phase 1:

- the repo has a stable `TrainingModule` contract
- the repo has a static registry and resolver
- AIMS is represented by a thin module adapter
- startup can validate and resolve the active module
- chat, session, storage, and Chainlit behavior remain unchanged

## Out Of Scope

Do not do any of the following in Phase 1:

- route chat through the registry
- move AIMS implementation files
- change API request or response shapes
- change Redis keying or archive shapes
- modularize frontend asset loading
- change Chainlit startup flow

## Why This Phase Exists

The current code needs a module seam before deeper refactors can be made
safely. Without a contract and registry:

- Phase 2 will freeze bad payload assumptions
- Phase 3 will route through ad hoc wrappers
- later storage and resume work will lack ownership boundaries

## Step-By-Step Plan

### Step 1: Extract the stable module metadata categories

Read only enough of the current code to define what the future module layer
must own. Use:

- `app/services/chat_orchestrator.py`
- `app/services/session_initializer.py`
- `app/services/chainlit/orchestrator.py`
- `app/services/storage_service.py`
- `app/services/summary_service.py`
- `app/services/chat_helpers.py`
- `app/memory_store.py`

Capture these categories:

- module identity
- branding/UI metadata
- dialogue role definitions
- startup capability flags
- persistence namespace metadata
- resume validation metadata

Do not try to standardize runtime behavior yet.

### Step 2: Create the new package skeleton

Add:

- `app/core/__init__.py`
- `app/core/module_types.py`
- `app/core/interfaces.py`
- `app/core/registry.py`
- `app/modules/__init__.py`
- `app/modules/aims/__init__.py`
- `app/modules/aims/module.py`

This should be additive only.

### Step 3: Define low-volatility types first

Add strongly typed metadata objects before the module protocol:

- `ModuleManifest`
- `BrandingSpec`
- `DialogueRoles`
- optional `ModuleCapabilities`

Recommended `ModuleManifest` fields:

- `id`
- `display_name`
- `chat_profile_name`
- `archive_schema_version`
- `storage_prefix`
- `dialogue_roles`
- `supports_intro`
- `supports_feedback`
- `supports_summary`
- `frontend_js_bundles`
- `frontend_css`
- `branding`

Reason:

- these are needed later by storage, frontend, and resume work
- they are safer to stabilize now than turn-processing signatures

### Step 4: Define the `TrainingModule` protocol

Use a `Protocol`, not an abstract base class, unless later runtime needs force
otherwise.

The contract should include:

#### Required metadata-facing surface

- `manifest`
- `module_id`
- `display_name`
- `storage_prefix()`
- `dialogue_roles()`
- `get_ui_manifest()`
- `resume_validation(...)`

#### Declared now for later phases, but not yet used by runtime

- `initialize_session(...)`
- `build_startup_payload(...)`
- `build_startup_artifacts(...)`
- `handle_turn(...)`
- `format_module_response(...)`
- `build_system_instruction(...)`
- `build_history_projection(...)`
- `build_summary(...)`
- `build_archive_payload(...)`
- `build_jailbreak_fallback(...)`

Important constraint:

- avoid binding these signatures too tightly to today's `ChatRequest` and
  AIMS-shaped models

Use typed wrappers or conservative generic types where the future generic
schema is not finalized yet.

### Step 5: Define registry exceptions and invariants

Create explicit errors:

- `ModuleNotRegisteredError`
- `DuplicateModuleRegistrationError`
- `InvalidModuleManifestError`

Registry invariants should include:

- unique module ids
- non-empty storage prefixes
- non-empty archive schema versions
- valid dialogue role declarations

### Step 6: Implement a static registry

Implement an explicit registry API:

- `register(module)`
- `get(module_id)`
- `require(module_id)`
- `list_modules()`
- `get_active_module_id(...)`
- `get_active_module(...)`

Do not use:

- directory scans
- import-time auto-registration spread across packages
- decorator-driven discovery

Use explicit built-in module registration from one known place.

### Step 7: Create a thin AIMS adapter

Implement `AimsTrainingModule` in `app/modules/aims/module.py`.

This adapter should:

- expose AIMS manifest data
- expose AIMS dialogue roles
- expose AIMS storage prefix metadata
- expose AIMS branding metadata
- provide placeholders or thin pass-through methods for future behavioral hooks

It should not:

- instantiate model clients at import time
- create new orchestration logic
- move existing AIMS implementation files

### Step 8: Add minimal startup validation

Hook registry construction and active-module resolution into one low-risk
startup/config path.

Acceptable Phase 1 integration points:

- app startup validation
- a startup log line
- a debug/config path that reports active module metadata

Avoid integrating the registry into chat dispatch yet.

### Step 9: Add focused tests

Add tests for:

#### Registry behavior

- successful registration
- duplicate registration rejection
- unknown module lookup rejection
- deterministic built-in registration
- active-module resolution from configured default

#### Manifest validity

- storage prefix required
- archive schema version required
- dialogue role declarations valid

#### AIMS adapter conformance

- adapter conforms to `TrainingModule`
- adapter exposes expected manifest metadata

#### Non-invasiveness

- current chat flow does not depend on module dispatch yet

## Foreseen Problems And Mitigations

### Problem 1: The contract becomes secretly AIMS-shaped

Examples:

- it assumes persona/scenario startup
- it assumes patient/clinician roles
- it assumes coach output

Mitigation:

- make Phase 1 metadata-focused
- use neutral terms like `participant`, `artifact`, `feedback`, `dialogue_roles`

### Problem 2: Import-time side effects

The new module layer could accidentally initialize heavy runtime dependencies.

Mitigation:

- keep manifests mostly static
- no Vertex or storage initialization in module import paths
- explicit registry construction only

### Problem 3: The protocol freezes today's request/response shape

That would cause rework in Phase 2.

Mitigation:

- strongly type metadata now
- keep future turn/session payload signatures generic enough to evolve

### Problem 4: Registry construction becomes order-sensitive

Mitigation:

- no scattered import-side-effect registration
- one explicit registration function for built-in modules

### Problem 5: Later storage/resume needs are forgotten

Mitigation:

- include `storage_prefix`, `dialogue_roles`, and `resume_validation` now even
  though runtime will not consume them yet

## Acceptance Criteria

Phase 1 is complete only when:

1. `app/core/` exists with module types, protocol, and registry
2. `app/modules/aims/module.py` exists with a thin AIMS adapter
3. registry resolves the active module deterministically
4. startup can validate module metadata without changing chat behavior
5. new tests covering registry and adapter behavior pass
6. there is no user-visible change in chat/session/storage behavior

## Verification

Minimum verification:

```bash
git diff --check
.venv/bin/python -m compileall -q app tests
.venv/bin/python -m pytest -q tests/core tests/modules/aims
```

Then run targeted existing tests for any startup/config surfaces touched.
