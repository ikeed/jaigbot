# Phase 9: Role And Bootstrap Generalization

## Objective

Finish the core semantic work that Phase 8 intentionally deferred:

- remove AIMS-first role assumptions from shared chat/history helpers
- expose a genuinely generic session bootstrap transport
- preserve backward compatibility for the current AIMS shell while creating a
  cleaner module-facing contract for future modules

This phase should not yet tackle deployment-shell branding or broad docs
rewrites. It is about runtime semantics and transport shape.

## Why This Phase Exists

Phase 8 proved that a second module can route through the system, but it did so
by mapping itself back into an AIMS-shaped outward shell:

- `assistant` remains the canonical "other side" role in several helpers
- author labeling still assumes `Doctor` / `Assistant` / `Coach`
- session bootstrap still exports `character`, `scene`, `personaName`, and
  `initialCard`
- generic startup artifacts are collapsed to a single compatibility field

That is enough for proof, but it is not a stable base for additional modules.

## Required Inputs From Earlier Phases

- Phase 4 generic bootstrap types
- Phase 6 module-owned JS bundle loading
- Phase 8 second-module proof and deferred issue list

## Scope

### In Scope

- role semantics in core Python helpers
- bootstrap/session transport design and compatibility serializer strategy
- startup artifact transport
- active-module role-to-author mapping seam
- history formatting and role counting semantics where they still assume AIMS

### Out Of Scope

- login/duplicate page branding cleanup
- deployment-level CSS/theming ownership
- registry lifecycle consolidation
- retiring import-path shims

## Problems To Solve

### 1. Assistant-Centric Context And Concern Extraction

Current examples:

- `app/services/chat_context.py`
- `app/services/chat_helpers.py`

The core still assumes:

- last counterpart turn is always `assistant`
- concern extraction should read only `assistant`

That is AIMS-specific logic living in generic helpers.

### 2. Hardcoded UI Author Mapping

Current example:

- `app/chat_roles.py`

The shell still centers:

- `Doctor`
- `Assistant`
- `Coach`

That should become module-aware, or at minimum manifest-aware.

### 3. Compatibility-Shaped Bootstrap JSON

Current example:

- `app/core/session_serialization.py`

The outward bootstrap payload still privileges:

- `character`
- `scene`
- `persona`
- `personaId`
- `personaName`
- `initialCard`

This keeps the current shell working, but it means future modules cannot expose
their startup state cleanly.

### 4. Plural Startup Artifacts Collapse To One Field

The generic `SessionBootstrapPayload.artifacts` is plural, but serialization
only exposes the first artifact as `initialCard`.

That is a contract mismatch now, not just a future cleanup item.

## Implementation Plan

1. Design a versioned bootstrap transport.
   - Keep the current compatibility fields for existing AIMS and Chainlit UI.
   - Add a generic block such as:
     - `module`
     - `participantContext`
     - `moduleState`
     - `artifacts`
   - Make it explicit that compatibility fields are transitional aliases.

2. Update session bootstrap serialization tests first.
   - Add failing tests for:
     - plural artifacts
     - artifact metadata presence
     - interview bootstrap using generic fields
     - AIMS compatibility aliases still present

3. Refactor `serialize_session_bootstrap_payload(...)`.
   - Keep current top-level fields for compatibility.
   - Add the generic payload structure alongside them.

4. Introduce a module-aware author/role presentation seam.
   - Decide whether role-to-author display belongs in:
     - module manifest
     - a separate role presentation map
     - module frontend bundle only
   - Do not bake new domain strings into `app/chat_roles.py`.

5. Remove assistant-specific assumptions from shared helpers.
   - `ChatContextBuilder.person_last`
   - `extract_recent_concerns(...)`
   - `format_history(...)` if needed
   - Move any AIMS-only concern heuristics behind the AIMS module if they are
     not actually generic.

6. Update the interview proof module to use the new bootstrap shape directly.
   - It should stop relying solely on AIMS-era aliases for its primary state.

7. Update Chainlit startup consumers to prefer generic fields first.
   - Maintain compatibility fallback to old aliases during transition.

## Risks

### Risk 1: Breaking The Current AIMS Shell

Mitigation:

- additive transport only
- tests that assert old compatibility fields still exist

### Risk 2: Inventing A Role System That Is Too Clever

Mitigation:

- keep the first pass simple
- solve author labeling and counterpart-role semantics
- avoid building a full role taxonomy engine

### Risk 3: Splitting AIMS Behavior Across Core And Module Again

Mitigation:

- if a helper turns out to be domain-specific, move it back behind the AIMS
  module rather than generalizing it badly

## Verification

- focused unit tests for bootstrap serialization, chat context, chat helpers,
  and Chainlit startup consumers
- non-integration suite for regression coverage
- browser sanity check for startup shell if the rendered payload shape changes

## Done Means

- generic bootstrap payload is first-class in the transport
- multiple startup artifacts can be represented without lossy collapse
- shared helpers no longer assume `assistant` is the universal counterpart role
- role presentation is on a credible path away from hardcoded AIMS labels
- the current AIMS UI still works without forced frontend rewrites
