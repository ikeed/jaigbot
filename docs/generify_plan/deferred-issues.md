# Generify Deferred Issues

This file records issues intentionally deferred during the modularization
phases so they do not get lost.

## Phase 2

None currently.

## Phase 3

None currently.

## Phase 4

- Chainlit startup and UI rendering still assume an AIMS-style scenario-card
  experience (`initialCard`, persona naming, `present_scenario_card(...)`).
  The ownership seam is better now because `/session` is module-owned, but the
  frontend-facing bootstrap vocabulary is still compatibility-shaped and will
  need another pass only if a future module needs a meaningfully different
  startup shell.

## Phase 5

- Archive serialization now refuses to guess a module family for
  archive-shaped payloads that lack resolvable module metadata. Mixed-module
  buckets or cross-deployment archive readers would still need a broader
  legacy-adapter strategy once more than historical AIMS payloads matter.
- Summary capability is now module-owned, but there is still only one concrete
  rich summary payload shape in the repo. Phase 8 proved that the "no summary
  capability" path works, but it did not add a second fully featured summary
  schema to exercise cross-module reporting semantics.

## Phase 6

None currently.

## Phase 7

None currently.

## Phase 9

- The generic bootstrap transport now carries a first-class `module` block with
  `participantContext`, `state`, and plural `artifacts`, but the Chainlit shell
  still treats the first artifact as the one renderable startup surface. That
  is good enough for the current shell, not a finished multi-artifact UI model.

## Phase 10

- Generic product docs and `AGENTS.md` were updated, but AIMS-specific docs
  still intentionally dominate the repo. That is correct while AIMS remains the
  primary shipped module, but a future broader module rollout will need another
  documentation pass.

## Phase 11

- Legacy-module inference is now explicit, but it only recognizes historical
  AIMS data families. That is the right move for this repo today, but it is not
  a general cross-module migration system.

## Phase 12

- Startup-artifact presentation is now explicit and multi-artifact aware, but
  the shell model is still intentionally narrow: one primary artifact plus
  inline cards, with passive artifacts ignored until a later module needs a
  richer layout contract.
- Shared avatar ownership is still shell-level even though the browser
  role-label logic is now generic.

## Phase 13

- Historical planning and cleanup docs still mention some pre-move file paths
  intentionally as transition context. Those references are now marked
  historical, but the repo still carries that historical narrative in docs.

## Phase 14

- The old non-coaching AIMS path is now explicitly named
  `AimsLegacyFallbackHandler`, with `LegacyChatHandler` kept only as a
  compatibility alias. Removing that alias would be cleanup only.

## Phase 15

None currently.

## Phase 16

None currently.
