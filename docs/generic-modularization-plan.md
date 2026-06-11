# Master Plan: Generic Conversation-Training Platform

Note: this document began as the pre-implementation master plan. The
authoritative current status now lives in `docs/generify_plan/README.md`.
References in early assessment sections to paths such as `app/aims_engine.py`
or `app/services/classifier_service.py` are historical context for the
transition, not the current ownership model.

## Purpose

Refactor the application so the core platform is generic conversation-training infrastructure and AIMS becomes one module implemented on top of it.

The desired end state is not merely “AIMS code moved to a folder.” The goal is a platform that can support:

- AIMS vaccine-hesitancy training
- job interview training
- HR / difficult-conversation practice
- other structured conversation-training applications

without changing the core orchestration, storage, routing, or frontend shell.

## Planning Status

This document remains the high-level master plan.

Detailed implementation planning now lives under:

- [docs/generify_plan/README.md](/Users/craigburnett/PycharmProjects/AIMSBot/docs/generify_plan/README.md)

Current implementation status:

- Phases 1-14 are implemented
- remaining gaps and cleanup candidates are tracked in
  `docs/generify_plan/deferred-issues.md`

## Definition Of Done

This refactor is done only when all of the following are true:

1. The core app boots and runs without importing AIMS-specific logic directly.
2. All AIMS behavior is accessed through a standardized module contract.
3. Core models, routes, storage, config, and UI shell are agnostic to AIMS domain terms.
4. Adding a new training module requires no edits to core orchestration files.
5. A second module, even a thin stub, can be registered and exercised end to end.
6. Session archives and analytics clearly record which module produced them.
7. Existing AIMS behavior remains functionally intact during the migration.

## Early Decisions To Lock Down

These decisions should be made explicitly before implementation begins, because
they affect storage, resume behavior, and frontend loading.

### 1. Deployment Model

Recommended approach:

- design for multiple modules in one codebase
- implement the first rollout as one active module per deployment
- persist `module_id` from day one anyway

Reason:

- this keeps the first migration simpler operationally
- but avoids painting the platform into a corner where old sessions cannot be
  resumed safely once multiple modules exist

### 2. Module Discovery Strategy

Recommended approach:

- use an explicit registry first
- do not use dynamic discovery or `entry_points` in the first implementation

Reason:

- this is a mono-repo, not a plugin marketplace
- explicit registration is easier to reason about, test, and roll back
- dynamic discovery adds import-order, packaging, and startup-debugging
  complexity before it solves a real problem

Dynamic discovery can be revisited later if external module packaging becomes a
real requirement.

### 3. Compatibility Horizon

Define up front how long the platform will preserve:

- old API aliases
- old archive readers
- old session-state readers
- old frontend message names

Recommendation:

- preserve read compatibility for old archives and old sessions for longer than
  write compatibility
- stop creating legacy shapes before stopping the ability to read them

## Guiding Principles

1. **Behavior-preserving first.**
   This refactor should proceed in stages with compatibility layers, not as a rewrite.

2. **Contract before movement.**
   Define interfaces and boundaries before moving files.

3. **Core owns infrastructure; modules own pedagogy.**
   Session management, transport, storage, and the app shell belong to core.
   Scoring logic, patient behavior, feedback rules, and domain prompts belong to modules.

4. **Migrate with adapters, not flags everywhere.**
   Avoid scattering `if aims` logic across the codebase.

5. **Keep the first non-AIMS module in mind while designing.**
   A job-interview module should fit naturally if the abstractions are correct.

## Current Assessment

The codebase already has one useful seam:

- most AIMS runtime behavior is concentrated in a service cluster

But the rest of the app still assumes the product is AIMSBot.

### AIMS-Specific Areas Today

#### Backend / Domain

- `app/services/aims_*`
- `app/aims_engine.py`
- `app/prompts/aims*`, `classify_turn.txt`, `endgame_detector.txt`, `summary_analysis.txt`
- `app/services/classifier_service.py`
- `app/services/patient_reply_service.py`
- `app/services/prompt_builders.py`
- AIMS-shaped parts of:
  - `app/models.py`
  - `app/constants.py`
  - `app/config.py`
  - `app/services/storage_service.py`
  - `app/services/summary_service.py`

#### App Shell / Orchestration

- `app/services/chat_orchestrator.py` branches between AIMS coaching and legacy paths
- `app/services/session_initializer.py` assumes persona/scenario-card startup
- `app/services/chainlit/orchestrator.py` assumes intro gating, scenario flow, persona naming, and coaching messages
- `app/services/chainlit/ui_handler.py` hardcodes `Scenario Briefing` and coach formatting
- `/summary` is AIMS-only
- `/config` exposes AIMS-specific settings

#### Frontend / Product Shell

- `.chainlit/config.toml` name and branding
- `chainlit_app.py` chat profile name and loading text
- `public/js/platform/*`
- `public/training-ui.css`
- `public/aims_infographic.svg`
- login/duplicate templates and avatar titles

## Target Architecture

### Core Platform

Suggested new root:

- `app/core/`
  - interfaces and registry
  - generic request/response models
  - generic session/memory/history management
  - generic chat orchestration
  - generic Chainlit orchestration
  - generic storage/archive shell
  - generic UI metadata/config
  - generic startup artifact handling

### Modules

- `app/modules/aims/`
  - prompts
  - classifiers
  - simulated patient behavior
  - scoring/coaching/endgame logic
  - AIMS-specific analytics and summary logic
  - AIMS-specific frontend assets such as infographic

Future:

- `app/modules/interview/`
- `app/modules/hr/`
- `app/modules/<other>/`

## Core Design Move

Introduce a strict module contract and a module registry. The platform should talk only to the contract, not to AIMS implementation details.

## Proposed Module Contract

Create a protocol such as `TrainingModule` under `app/core/interfaces.py`.

It should include, at minimum:

- `module_id: str`
- `display_name: str`
- `supports_evaluation: bool`
- `supports_summary: bool`

### Session / Startup Hooks

- `initialize_session(...)`
- `build_startup_payload(...)`
- `recover_session_state(...)`
- `build_startup_artifacts(...)`

### Conversation Hooks

- `handle_turn(...)`
- `format_module_response(...)`
- `build_system_instruction(...)`
- `build_history_projection(...)`
- `dialogue_roles(...)`
- `build_jailbreak_fallback(...)`

### Analytics / Summary Hooks

- `build_summary(...)`
- `build_archive_payload(...)`
- `read_legacy_archive(...)` if needed

### Frontend / UI Hooks

- `get_ui_manifest()`
- `get_window_message_types()`
- `get_chat_profile()`

### Persistence / Resume Hooks

- `storage_prefix(...)`
- `resume_validation(...)`

These are not optional details. They are part of the module boundary because
the current code already shows domain coupling in persistence and resume.

## Proposed Registry

Create `app/core/registry.py` or `app/modules/registry.py`.

Responsibilities:

- register modules
- resolve active module from config/session/request
- expose module manifests to backend and frontend

Suggested manifest fields:

- `id`
- `display_name`
- `chat_profile_name`
- `branding`
- `startup_mode`
- `frontend_css`
- `frontend_js_bundles`
- `icons`
- `supports_intro`
- `supports_evaluation`
- `supports_summary`
- `storage_prefix`
- `dialogue_roles`
- `archive_schema_version`

## Core Refactor Plan

### Phase 0: Prep And Inventory

Before any architecture change:

1. freeze current AIMS behavior with regression coverage around:
   - chat responses
   - session startup
   - Chainlit resume
   - summary
   - archive format
2. inventory all AIMS-specific names and payload shapes
3. identify which files are platform candidates vs module candidates
4. inventory all persisted-state shapes, not just Python modules

Deliverables:

- migration inventory
- compatibility list
- test baseline

The persisted-state inventory should explicitly include:

- Redis key patterns and prefixes
- in-memory session shape
- GCS archive schema versions
- Chainlit thread metadata
- current-thread pointers
- frontend query parameters
- window-message names and payloads

### Phase 1: Contracts And Registry

Add:

- `TrainingModule` protocol
- module registry
- `ActiveModuleResolver`

No behavior change yet.

Acceptance criteria:

- AIMS can be wrapped in an adapter that satisfies the contract
- core still behaves exactly as before

### Phase 2: Generic Response And Request Schema

Current risk:

- `app/models.py` is AIMS-shaped (`Coaching`, `ClassifierResult`, `SessionMetrics`, `coach`)

Refactor toward:

- generic request model
- generic response model
- module-scoped payloads

Suggested generic response shape:

- `reply`
- `session`
- `module`
- `evaluation`
- `artifacts`
- `events`
- optional `completion`

Suggested request changes:

- replace `coach` with something module-neutral or move it into a generic module options block
- preserve backward compatibility during transition

The request/session envelope should also persist:

- `module_id`
- schema version
- startup artifact metadata as generic types, not AIMS-specific fields

Acceptance criteria:

- core models do not mention AIMS steps or phases
- AIMS-specific payload models live in `app/modules/aims/models.py`

### Phase 3: Orchestrator Decoupling

#### Backend chat orchestrator

`ChatOrchestrator` should:

- validate input
- build generic context
- resolve active module
- delegate `handle_turn(...)`
- normalize generic response envelope

It should no longer branch between:

- AIMS coaching path
- legacy path

It also should not assume that every module is a:

- scenario-based simulator
- patient/clinician dialogue
- coaching workflow

#### Chainlit orchestrator

Refactor `app/services/chainlit/orchestrator.py` into:

- generic shell behavior
- module hooks for:
  - startup
  - resume
  - startup artifacts
  - module-specific messages

Acceptance criteria:

- no AIMS-specific flow assumptions in core orchestrators
- module selection is explicit and visible in logs / diagnostics

### Phase 4: Move AIMS Under `app/modules/aims/`

Relocate and re-home:

- `app/services/aims_coaching_handler.py`
- `app/services/aims_*`
- `app/aims_engine.py`
- `app/services/classifier_service.py`
- `app/services/patient_reply_service.py`
- `app/services/prompt_builders.py`
- all AIMS prompt files
- AIMS-only summary logic

Suggested end state:

- `app/modules/aims/handler.py`
- `app/modules/aims/models.py`
- `app/modules/aims/prompts/`
- `app/modules/aims/services/`
- `app/modules/aims/assets/`
- `app/modules/aims/frontend/`

Acceptance criteria:

- all AIMS-specific imports originate from `app.modules.aims`
- core files no longer import `app.aims_engine` or AIMS prompt modules

### Phase 5: Session Initialization And Startup Artifact Generalization

`session_initializer.py` currently assumes:

- persona
- character
- scene
- initial scenario card

Those fields are not generic enough to remain the core session shape forever.
They may survive temporarily as compatibility fields, but the long-term session
bootstrap model should be closer to:

- `module_id`
- `counterparty_profile`
- `startup_artifacts`
- `module_state`
- `session_metadata`

Refactor the platform to support generic startup artifacts:

- scenario card
- intro modal
- document/infographic
- instructions
- module-specific briefing

Suggested core type:

- `StartupArtifact`
  - `kind`
  - `payload`
  - `render_hint`

Acceptance criteria:

- core session bootstrap does not assume a scenario card exists
- active module controls startup artifacts
- startup payload shape can support non-persona modules cleanly

### Phase 6: Frontend Shell Split

Split frontend into:

- generic platform shell
- module-specific bundles

Suggested structure:

- `public/js/platform/*`
- `public/modules/aims/*`

Generic:

- modal plumbing
- logout/new-chat/session controls
- duplicate-tab handling
- thread resume shell
- generic message decoration

Module-specific:

- infographic modal
- AIMS startup copy
- AIMS-specific icons
- AIMS-specific coach presentation

Important constraint:

- Chainlit gives the app one `custom_js` and one `custom_css` entry point

Recommended strategy:

- keep one generic bootstrap loader in Chainlit config
- have that loader fetch the active module manifest
- load generic shell first
- then load module assets deterministically from the manifest

Do not try to make Chainlit config itself vary per module or per session.

Acceptance criteria:

- platform can run with no AIMS-specific JS loaded
- AIMS module opts into its own assets through manifest

### Phase 7: Message Vocabulary Cleanup

Current AIMS-specific window messages include:

- `aims_intro_required`
- `aims_resume_thread`
- `aims_persona_name`
- `aims_new=1`

Replace with generic vocabulary:

- `module_intro_required`
- `resume_thread`
- `participant_name`
- `new_session=1`

Then allow modules to define additional namespaced messages if necessary.

Go one step further and define a standard lifecycle vocabulary for the shell:

- `training_start`
- `training_feedback`
- `training_artifact`
- `training_resume`

Modules can still emit additional namespaced events, but the shell should not
need to know whether feedback came from AIMS, interview scoring, or another
training domain.

Acceptance criteria:

- no AIMS-prefixed messages in core JS or core Python

### Phase 8: Storage, Archive, And Summary Generalization

Current storage writes AIMS-shaped fields:

- `analytics.aims`
- `conversationState: aims_state`
- `summary: coach_post`

Refactor to a module-aware archive format:

```json
{
  "metadata": { ... },
  "module": {
    "id": "aims",
    "version": "v1"
  },
  "transcript": [ ... ],
  "analytics": {
    "module": "aims",
    "payload": { ... }
  },
  "summary": {
    "module": "aims",
    "payload": { ... }
  }
}
```

The core storage service should not understand AIMS internals.

Important additional requirement:

- new session-memory keys must be module-namespaced early in the migration

Recommended key strategy:

- `module:{module_id}:session:{session_id}`

This should be addressed at the start of the migration, not left for later,
because cross-module persistence contamination is one of the easiest ways to
create hard-to-debug failures.

Acceptance criteria:

- archive schema supports arbitrary module payloads
- old AIMS archives can still be read

### Phase 9: Config And Branding Generalization

Refactor:

- `AIMS_COACHING_ENABLED`
- `AIMS_COACHING_DEFAULT`
- redis prefix `aims`
- bucket names tied to aimsbot
- login titles and app names

Toward:

- `ACTIVE_MODULE`
- `DEFAULT_MODULE`
- module-specific config namespace
- generic storage prefix
- platform title plus module display name

Acceptance criteria:

- app can boot with another selected module and coherent branding

### Phase 10: Test Reorganization

Split tests into:

- `tests/core/`
- `tests/modules/aims/`

Core tests:

- session behavior
- generic orchestration
- archive shell
- module resolution
- frontend shell behavior

Module tests:

- AIMS scoring
- AIMS patient reply generation
- AIMS summary
- AIMS resume/startup behavior

Acceptance criteria:

- core tests do not rely on AIMS terms
- AIMS regressions remain covered

## Compatibility Strategy

This refactor should explicitly support a transition period.

### API Compatibility

Current clients expect:

- `coach`
- `coaching`
- `coachPost`

Mitigation:

1. add generic fields first
2. keep old AIMS aliases temporarily
3. migrate Chainlit/frontend to generic fields
4. remove old aliases only after all callers move

### Storage Compatibility

Existing Redis/GCS records are AIMS-shaped.

Mitigation:

1. tag new archives with module metadata and schema version
2. add AIMS compatibility reader for old records
3. keep old archive writer optional during migration if needed
4. introduce versioned adapters rather than one-off conditionals

Recommended pattern:

- `AimsLegacyArchiveAdapter`
- `GenericModuleArchiveAdapter`

The storage layer should detect `schema_version` or `module_id` and dispatch to
an adapter instead of accumulating implicit migration logic in the core writer.

### Session Compatibility

Current memory keys include:

- `aims_state`
- `aims`
- `coach_post`

Mitigation:

1. keep legacy reads in AIMS module
2. move new writes under module-owned namespace
3. only remove direct core usage once the module fully owns them
4. persist `module_id` inside session memory itself
5. persist `module_id` inside Chainlit thread metadata and archives

Resume must use the stored `module_id`, not the deployment default.

If a module is unavailable at resume time, define explicit fallback behavior:

- refuse resume and show a recoverable message
- or start a new session only if policy explicitly allows it

Do not silently resume old sessions under a different module.

## Recommended Directory Layout

Suggested eventual shape:

```text
app/
  core/
    interfaces.py
    registry.py
    models.py
    chat_orchestrator.py
    session_initializer.py
    summary_service.py
    storage_service.py
    chainlit/
      orchestrator.py
      ui_handler.py
  modules/
    aims/
      __init__.py
      module.py
      models.py
      prompts/
      services/
      assets/
      frontend/
    interview/
      __init__.py
      module.py
```

Note: do not force this exact directory move all at once. It is a target layout, not a first patch.

## Additional Problems To Anticipate And Mitigate

### 1. False genericity

Risk:

- abstractions are written in AIMS language and only renamed superficially

Mitigation:

- validate every new interface against a non-healthcare example
- review core types for domain words like `vaccine`, `clinician`, `patient`, `scenario`, `coach`

### 2. Over-generalization too early

Risk:

- trying to solve every future module design before the first module contract is proven

Mitigation:

- design for AIMS plus one plausible second module
- do not invent abstractions that no current or near-term module needs

### 3. Prompt ownership confusion

Risk:

- core still builds prompts while modules partially own prompt content

Mitigation:

- module owns domain prompts entirely
- core should only own transport-independent prompt composition helpers if they are truly generic
- avoid leaving a permanent core assumption that every module has a
  `character` and a `scene`
- move domain-specific fallback utterances, concern extraction, and role-play
  framing into modules

Concrete examples already visible in the current app:

- `build_system_instruction(...)` still assumes character/scene framing
- `extract_recent_concerns(...)` is AIMS-specific but currently in shared helper
- jailbreak fallback text in patient-reply logic is domain-specific

### 4. UI loader complexity

Risk:

- module assets become dynamically loaded in brittle ways that are hard to reason about

Mitigation:

- define a deterministic frontend manifest
- load generic shell first, then module bundle(s)
- version and cache-bust module bundles cleanly

### 5. Resume / stale-session regressions

Risk:

- session restoration logic breaks when core no longer assumes scenario/persona structure

Mitigation:

- keep resume behavior under regression tests
- define a generic persisted-thread validation contract
- let modules contribute startup recovery logic without replacing core safety checks
- make current-thread pointers module-aware
- ensure module mismatch is treated as a first-class resume failure mode

### 6. Archive analysis lock-in

Risk:

- `/summary` and analytics stay AIMS-shaped under a “generic” wrapper

Mitigation:

- make summary generation an explicit module capability
- support “module has no summary” cleanly

### 7. Legacy naming spread

Risk:

- old `aims_*` names persist across templates, query params, CSS classes, and tests

Mitigation:

- maintain a migration checklist for:
  - env vars
  - query params
  - message types
  - CSS classes
  - archive fields
  - route docs
  - tests

### 8. Mixed ownership of personas

Risk:

- `persona_service` stays in core but really belongs to modules

Mitigation:

- separate generic participant-profile loading from AIMS persona selection
- likely move persona selection into modules, while keeping profile-loading utilities generic if useful

### 9. Bucket / prefix collisions

Risk:

- generic modules write into old aimsbot-named stores and create confusing mixed data

Mitigation:

- add module id to archive metadata and optionally to object path
- review Redis key prefix strategy before enabling multiple modules in the same environment
- put the module namespace into keys before introducing a second module

### 11. Role-model leakage in core history management

Risk:

- core history trimming and formatting silently assume one domain's role model

Mitigation:

- let the module declare which roles count as dialogue roles
- let the module declare which roles count as evaluative or metadata roles
- avoid hardcoding `ROLE_COACH` or `ROLE_ASSISTANT` semantics in core

This matters because a future interview module may use roles like:

- `interviewer`
- `candidate`
- `observer`

and those are not equivalent to the current AIMS dialogue assumptions.

### 12. Telemetry blind spots

Risk:

- once multiple modules exist, logs and metrics become difficult to interpret

Mitigation:

- include `module_id` in:
  - session bootstrap responses
  - telemetry events
  - request logs
  - archive metadata
  - health / debug diagnostics where appropriate

### 13. Neutral test fixtures not actually neutral

Risk:

- core tests keep using AIMS-shaped fake data, which hides coupling

Mitigation:

- introduce neutral core fixtures
- make module tests own persona/scenario/coach-specific fixtures
- add at least one second-module stub to prove the core fixture set is truly generic

### 10. Operational rollout risk

Risk:

- large migration lands without a rollback path

Mitigation:

- keep module selection behind config
- support `ACTIVE_MODULE=aims` as the default until generic infrastructure is proven
- preserve old API aliases until the frontend is fully migrated

## Suggested Execution Order

This is the recommended order of implementation:

### Step 0

Inventory persisted shapes and lock the early architecture decisions.

### Step 1

Write the concrete `TrainingModule` protocol and explicit registry.

### Step 2

Introduce generic response wrappers and compatibility aliases.

### Step 3

Move persistence namespacing and `module_id` propagation into the design early.

That includes:

- Redis prefixes
- session-memory payloads
- archives
- Chainlit thread metadata
- current-thread pointers

### Step 4

Adapt AIMS into the contract without moving all files yet.

### Step 5

Refactor `ChatOrchestrator` to use module dispatch.

### Step 6

Generalize session bootstrap and startup artifacts.

### Step 7

Generalize archive and summary services.

### Step 8

Split frontend shell from AIMS frontend bundle.

### Step 9

Move AIMS files into `app/modules/aims/`.

### Step 10

Clean up config, naming, and tests.

### Step 11

Add a minimal second module stub to prove the design.

## Acceptance Gates By Phase

### Gate A: Interface Gate

- AIMS can be wrapped as a `TrainingModule`
- no behavior change

### Gate B: Orchestration Gate

- chat flow works through module dispatch
- current AIMS sessions still behave the same
- module selection and resume path are visible and testable

### Gate C: Storage Gate

- old archives still load
- new archives record module id and schema version
- new session keys are module-namespaced
- stored `module_id` survives resume

### Gate D: Frontend Gate

- generic shell runs
- AIMS bundle loads on top without regressions
- Chainlit custom loader remains single-entry and deterministic

### Gate E: Extensibility Gate

- a second stub module can be selected without touching core files

## Anti-Goals

These are not part of this refactor:

- redesigning the visual system
- changing the educational behavior of AIMS itself
- rewriting all prompts for quality improvements unrelated to modularization
- replacing Chainlit
- redesigning Vertex integration just because modules are being introduced

## Recommended Immediate Next Step

Before any code movement, create a shorter implementation design doc that specifies:

1. the exact `TrainingModule` protocol
2. the registry API
3. the generic response envelope
4. the archive schema versioning strategy
5. the compatibility plan for old AIMS API fields

That design doc should be the gate before implementation starts.
