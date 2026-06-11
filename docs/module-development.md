# Module Development Guide

This repo now has a generic training-platform core plus module-owned domain
logic. New modules should plug into the existing contract instead of
reintroducing domain-specific behavior into `app/core/`, shared routes, or the
frontend shell.

## Where Module Code Lives

- Module implementation: `app/modules/<module_id>/`
- Module entrypoint: `app/modules/<module_id>/module.py`
- Module docs: `app/modules/<module_id>/docs/`
- Module prompts/assets/services: keep them under the same module directory

Shared core code belongs in:

- `app/core/` for cross-module contracts, serialization, archive/session types,
  and registry/runtime helpers
- `app/services/` only for genuinely shared infrastructure that is not owned by
  one module

## The Contract

The standard interface is [app/core/interfaces.py](../app/core/interfaces.py).
All built-in modules conform structurally to `TrainingModule`.

The most important required pieces are:

- `manifest`
- `module_id`
- `display_name`
- `storage_prefix()`
- `dialogue_roles()`
- `get_ui_manifest()`
- `resume_validation(...)`
- `initialize_session(...)`
- `handle_turn(...)`
- `format_module_response(...)`
- `build_summary(...)`
- `build_archive_envelope(...)`

Some hooks are still future-facing and may remain `NotImplementedError` until
the runtime actually routes through them. Do not invent parallel abstractions
for those hooks.

## Manifest Requirements

The low-volatility module metadata lives in
[app/core/module_types.py](../app/core/module_types.py)
as `ModuleManifest`, `DialogueRoles`, and `BrandingSpec`.

Every module must define:

- `id`
- `display_name`
- `chat_profile_name`
- `archive_schema_version`
- `storage_prefix`
- `dialogue_roles`

Optional but useful fields:

- `supports_intro`
- `supports_feedback`
- `supports_summary`
- `frontend_js_bundles`
- `frontend_css`
- `branding`

Registry validation already enforces:

- non-empty module id
- non-empty storage prefix
- non-empty archive schema version
- at least one participant role

## Dialogue Roles

`DialogueRoles` is not decorative. Shared services use it to understand:

- which roles are participant turns
- which roles count toward history trimming and metrics
- which roles are user-facing vs counterpart-facing
- how the frontend should label participants

If a module has distinct feedback or observer roles, declare them explicitly.
Do not rely on AIMS-era defaults like `assistant` or `coach`.

## Session Bootstrap

Module startup should produce a
[SessionBootstrapPayload](../app/core/session_types.py)
and then serialize through
[app/core/session_serialization.py](../app/core/session_serialization.py).

Current expectations:

- startup artifacts are ordered
- hidden artifacts are ignored by the Chainlit startup renderer
- multiple visible artifacts are supported
- compatibility fields like `character`, `scene`, and `initialCard` still
  exist for older shell paths, but new module logic should treat
  `module.participantContext`, `module.state`, and `module.artifacts` as the
  canonical structure

## Turn Handling

`handle_turn(...)` is where the module owns its domain behavior.

Inputs come in through keyword args today. In practice the important ones are:

- `body`
- `ctx`
- `memory_store`
- `vertex_config`
- `memory_config`
- `module_runtime_config`
- `logger`

Guidelines:

- own domain branching inside the module
- update memory/history with module-defined roles
- return a neutral result mapping
- let `format_module_response(...)` shape the platform response payload

Do not push module-specific branching back into
`app/services/chat_orchestrator.py`.

## Summary And Archive Ownership

Modules own their summary payloads and archive envelopes.

- `build_summary(...)` returns module-defined summary data
- `build_archive_envelope(...)` returns a
  `ModuleArchiveEnvelope`

Keep these rules:

- transcript role semantics should match the module’s `DialogueRoles`
- archive metadata must include `moduleId`
- compatibility payloads should be intentional, not accidental copies of AIMS

## Frontend Integration

If a module needs frontend code:

- declare module JS bundles in `manifest.frontend_js_bundles`
- declare a module or shared stylesheet in `manifest.frontend_css`
- prefer shared platform shell code under `public/js/platform/`
- keep module-specific behavior under `public/js/modules/<module_id>/`

Per-module branding, loading text, and avatars belong in `manifest.branding`.

## Registration

Built-in modules are registered statically in
[app/core/registry.py](../app/core/registry.py)
via `build_builtin_registry(settings=...)`.

Current project policy:

- use the static registry
- do not add dynamic module discovery
- register new built-in modules explicitly in one place

## Testing Expectations

At minimum, add:

1. Manifest/contract tests
2. Session bootstrap test
3. Turn-handling test
4. Summary and archive test

The interview module tests are the best small example:

- [tests/unit/modules/interview/test_interview_module.py](../tests/unit/modules/interview/test_interview_module.py)

There is also a higher-level round-trip test pattern in:

- [tests/unit/core/test_module_roundtrip.py](../tests/unit/core/test_module_roundtrip.py)

For shared-runtime changes, also run:

```bash
.venv/bin/python -m pytest --ignore=tests/integration -q
```

## Anti-Patterns

Do not:

- add AIMS-specific fields back into `app/core/`
- hardcode `assistant`, `coach`, or AIMS-specific startup assumptions in shared
  services
- introduce a second registry or alternate module-loading path
- put module docs back under root `docs/` if they are clearly module-owned
- bypass `ModuleManifest` for branding or frontend bundle discovery

## Good Starting References

- [app/core/interfaces.py](../app/core/interfaces.py)
- [app/core/module_types.py](../app/core/module_types.py)
- [app/core/registry.py](../app/core/registry.py)
- [app/modules/interview/module.py](../app/modules/interview/module.py)
- [app/modules/aims/module.py](../app/modules/aims/module.py)
