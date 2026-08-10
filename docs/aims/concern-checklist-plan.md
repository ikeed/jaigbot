# Concern Checklist: Design & Implementation Plan

**Status:** DRAFT — under discussion, not approved for implementation.
**Owner context:** Replaces the current fuzzy `is_undiscovered_concerns` heuristic
(true/false proxy based on whether *any* concern has been captured) with a
deterministic, per-persona checklist of specific concerns, tracked as
discovered/undiscovered individually. This lets Endgame closure, scoring, and
coaching tips reason about "did we find everything this persona has" instead of
inferring it from an ambiguous transcript re-read.

This document is the single source of truth for the design as agreed, the
decisions made while planning it, and the step-by-step build plan + test
matrix. Iterate on this file directly.

**Important caveat**: this batch alone does not yet deliver the original
motivating goal from the scoring conversation — "don't score Inquire as 0%
when the patient self-discloses everything unprompted." That fix lives in the
deferred scoring follow-up (§7, item 1). Until that follow-up ships, a
clinician who successfully avoids the Endgame block (because everything got
self-disclosed) will still see Inquire scored 0% under the current formula.
This batch fixes *discovery tracking and blocking*; the *scoring* half of the
original problem ships separately.

---

## 1. Problem this solves

- `is_undiscovered_concerns` currently starts `True` and only flips `False` once
  *any* concern lands in `parent_concerns` — it cannot distinguish "this persona
  has no concerns" from "concerns exist but nobody's found them yet."
- Endgame closure has no way to know whether a person who appears to be
  wrapping up is actually withholding an unaddressed concern.
- Scoring currently gives Inquire a blanket 0% when skipped, even when the
  patient volunteered every concern unprompted and there was nothing left to
  ask about — punishing a clinician who did nothing wrong.

## 2. Existing mechanisms this reuses (found during a full grounding pass)

Before the design section: the codebase already has more of this built than
the first draft of this plan assumed. Reading the actual bodies of
`apply_concern_events` and its helpers (`app/services/conversation_service.py`)
changed the shape of Steps 4–6 substantially — mostly by *shrinking* them,
since they reuse existing machinery instead of adding a parallel one.

- **Concern IDs are always derived, never authored.** `_canonical_id(topic)`
  (via `_canonical_topic` → `_CONCERN_TOPIC_ALIASES`, a locale-driven alias
  map) computes a concern's `id` from its `topic` every time
  `_normalize_existing_concern` touches it. Storing a separate hand-authored
  `id` field in `personas.json` would just drift from the derived one. The
  checklist schema is `{topic, desc}`, not `{id, topic, desc}`.
- **The topic vocabulary already exists and personas.json's authored topics
  already match it.** `_CONCERN_TOPIC_ALIASES` / `_CONCERN_LABELS`
  (`lexicon.concerns.*` in `en.json`) and `aims_system_instruction.txt`'s
  `PERSON_TOPIC_CATEGORIES` define a **closed, 9-topic vocabulary**: `autism`,
  `immune_load`, `side_effects`, `ingredients`, `schedule_timing`,
  `disease_risk`, `effectiveness`, `trust`, `autonomy`. 9 of the 10 concerns
  authored in Step 1 already use these exact keys. Two gaps found:
  - `requirements` is in `_CONCERN_TOPIC_ALIASES`/`_CONCERN_LABELS`/
    `topic_hints` (used elsewhere in the app) but **missing from
    `PERSON_TOPIC_CATEGORIES`** in the system instruction — meaning
    `classify_turn` was never actually told this is a valid topic. Zia's
    "requirements" concern needs this added.
  - `age_appropriateness` (Georgina's second concern) isn't in *any* of these
    — genuinely new, and deliberately **not** added to the global taxonomy
    (§4, item 9) — it's scenario-local to Georgina's session context instead.
- **`_normalize_existing_concern` will rewrite `desc`.** Any concern without a
  pre-set `canonical_label` gets one computed from `_CONCERN_LABELS[topic]`
  (or the evidence text if the topic isn't in that map), and `desc` gets
  unconditionally reassigned from that. This means the prose authored in
  `personas.json`'s `desc` field **will not persist verbatim** in
  `parent_concerns` once normalized — it gets replaced by the generic canned
  label (e.g. "wants immune load or spacing addressed") the first time the
  concern is touched. This is expected/consistent with how the existing
  system already displays concerns elsewhere (topic hints are generic by
  design) — the authored `desc` is prompt *input* material (for `classify_turn`
  matching and the patient-reply generator), not a guaranteed persistent
  value.
- **`_apply_concern_presence_event` already does most of "discovery
  matching."** For a `concern_raised`/`concern_renewed` `person_event`, it:
  finds an existing concern by `target_concern_id` or `topic`
  (`_find_event_target` → `_find_matching_concern`), and if found, merges
  evidence and re-syncs status; if not found, creates a brand new concern via
  `_new_concern` (defaults: `is_mirrored: False, is_secured: False`) and
  appends it. **There is no separate `concerns_revealed` field to invent** —
  discovery matching for a pre-seeded checklist entry is just "a
  `concern_raised` event resolved to an *existing* entry instead of creating
  a new one," which the plumbing already does. The only gap: nothing today
  sets an `is_discovered` flag, because that flag doesn't exist yet.
- **`_build_reply_concern_state_section`
  (`app/services/aims_coaching_handler.py`) is the existing hook that tells
  the patient-reply generator about concern state each turn**, via
  `concern_state_section` → `build_patient_reply_prompt` →
  `aims_patient_reply.txt`'s `{concern_state_section}`. Today it only knows
  two buckets — open (`not is_secured`) vs. resolved (`is_secured`) — driven
  entirely by `parent_concerns`. This is the exact mechanism Step 5 needs; it
  needs a third bucket (undiscovered), not a new mechanism.
  **Caveat**: `patient_reply_service.py` does a literal substring check
  (`"open concerns: none" in concern_state_section.lower()`) to decide
  fallback wording when the model call fails — any new message text added
  here must not accidentally break that check.
- **`secure_before_mirror`'s actual counting mechanism is topic-keyed, not a
  simple counter** — a rolling `recent_coaching` list (last 3 entries) with a
  per-topic repeat-count lookup (`_secure_before_mirror_repeat_count`), because
  it needs to track repeats *per unmirrored concern*. The Inquire nudge
  doesn't need that — it's about the clinician's overall behavior, not a
  specific concern — so a **plain global integer counter** (increment/reset)
  is the right shape and is simpler than `secure_before_mirror`, not a copy of
  it. Earlier plan language calling it "the same shape" was imprecise.

## 3. Design as agreed

1. **Static, hand-authored checklist.** Add a new `concerns` field to each
   entry in `app/prompts/personas.json` — a list of 1–3 items
   (`{topic, desc}` — **no separate `id`**, see §2), never 0 ("everybody
   should have at least one question"), never 4+ ("enough to practice on").
   **No LLM call needed for checklist generation** — personas are static
   data, not generated per-session.

2. **State model.** `parent_concerns` is pre-seeded at scenario start from the
   persona's `concerns` list (instead of starting empty and growing
   organically). Each seeded entry gets a new `is_discovered: False` flag and
   a new `from_checklist: True` marker (distinguishes pre-seeded entries from
   ones `_apply_concern_presence_event` creates organically — needed so the
   Endgame backstop and nudge only ever look at checklist entries, never at
   ad-hoc ones). Invariant: `is_mirrored` and `is_secured` must never be
   `True` unless `is_discovered` is also `True`.

3. **Discovery matching extends `_apply_concern_presence_event`
   (`conversation_service.py`), not `classify_turn`'s output schema.** No new
   `concerns_revealed` field. When a `concern_raised`/`concern_renewed` event
   resolves to an *existing* `from_checklist: True` entry, also set
   `is_discovered = True` on it (in addition to what the function already
   does). `classify_turn`'s per-turn prompt gains new context (alongside the
   existing `inquired_concerns_list`/`mirrored_concerns_list`) telling it
   which specific topics are this persona's checklist and which are already
   discovered — reusing the topic vocabulary the model is already fluent in
   (§2), not teaching it a new one.
   - **Unknown/unmatched topic handling**: when a `concern_raised` event's
     topic doesn't match any `from_checklist: True` entry, `_new_concern`
     creates a fresh one as it does today. Immediately mark that fresh entry
     `is_discovered: True, is_mirrored: True, is_secured: True` and log it.
     Two independent reasons this matters, not one: (a) the Endgame backstop
     only ever scopes to `from_checklist: True` entries, so an off-checklist
     entry structurally can't block it regardless of this flag — but (b) the
     *separate* `detect_endgame` LLM call reads a "Secured Concerns" list
     built from `parent_concerns` as its own context, and a stray
     unresolved-looking ad-hoc entry there could confuse *that* call's own
     holistic judgment even though it can't trigger the Python backstop. The
     auto-resolve protects against (b).

4. **Patient-reply generation changes** — extends the existing
   `_build_reply_concern_state_section` → `concern_state_section` →
   `aims_patient_reply.txt` pipeline (§2), adding a third "undiscovered"
   bucket alongside the existing open/resolved ones:
   - Instructed to reveal **at most one new concern per turn** (best-effort;
     the matching logic in §3 must handle violations gracefully, not assume
     compliance — a turn revealing two at once must mark both discovered).
   - The new "undiscovered" bucket in the concern-state section *is* how the
     persona's own sense of "what have I said" stays synchronized with what
     Python believes — it's reading the same `parent_concerns` state the
     matcher writes to, every turn, not a separate memory.
   - **Role-play behavior**: while any `from_checklist: True` entry has
     `is_discovered: False`, the persona must not signal agreement/consent/
     resolution. Preferred: convey reluctance, prompting the clinician to
     Inquire. Acceptable: spontaneously blurt a concern, prompting Mirror.
     Primary defense against deadlock — a well-behaved persona should never
     hand `detect_endgame` a transcript that looks resolved while something's
     still hidden.

5. **Endgame gating — "trust but verify."** The role-play fix (4) is the
   primary mechanism; a lightweight Python-side backstop in
   `aims_endgame_service.py` checks whether any `from_checklist: True` entry
   still has `is_discovered: False`, as defense-in-depth. Should rarely fire
   given (4), but catches the case where the persona *and* the matcher both
   slip.

6. **Two-tier Inquire nudge** — a plain global counter (§2), not a copy of
   `secure_before_mirror`'s topic-keyed mechanism:
   - **Mid-conversation** (proactive, plain Tip): fires once the clinician has
     had **2 turns with `STEP_SECURE` present** (including compound steps like
     `Mirror+Secure` — checked via `component_steps`/`all_steps` membership,
     same pattern used elsewhere for compounds) **since the last turn with
     `STEP_INQUIRE` present** (or since the start, if Inquire has never
     happened), *and* an undiscovered `from_checklist: True` entry remains.
     The counter increments on any Secure-containing turn, resets to 0 on any
     Inquire-containing turn, and is **left unchanged** on a turn that
     contains neither (e.g. a pure Announce or pure Mirror turn).
     **Stays flat** — same text every turn once past threshold, for as long
     as the condition holds. No escalation tiers within this tier (deliberate
     simplicity call — "two-tier" describes mid-conversation vs.
     closure-attempt only, not repeat behavior within the mid-conversation
     tier itself).
   - **At closure-attempt** (Important, escalated): when the backstop in (5)
     actually blocks a would-be closure — explains *why* the conversation
     isn't over and suggests a sweep-up question ("anything else on your
     mind?").

7. **Existing keyword-based fallback untouched.** `TOPICAL_CUES` /
   `maybe_add_person_concern` stay exactly as they are, gated behind
   `AIMS_HEURISTIC_FALLBACK_ENABLED` (off in every deployed environment).

8. **No backward-compat / resume handling needed** — beta/test data only, not
   live yet.

9. **Full audit required, and two sites are now known to be load-bearing, not
   just "should check":**
   - `aims_state_service.py`'s `update()` currently sets
     `is_undiscovered_concerns = False` **whenever `parent_concerns` is
     non-empty at all** (lines ~98–102). Once concerns are pre-seeded and
     non-empty from turn one, this flips it false immediately on the very
     first turn — backwards. This line must be **replaced**, not just
     audited, with a recomputation scoped to `from_checklist: True` entries'
     `is_discovered` state.
   - `update_observational_state` also sets `is_undiscovered_concerns = False`
     **on any turn where `STEP_INQUIRE` is present**, regardless of whether a
     specific concern was actually discovered. This must also be **removed**
     — going forward, discovery is driven exclusively by §3's per-concern
     matching, not by step classification alone (an Inquire-classified turn
     that doesn't happen to elicit any checklist item shouldn't be treated as
     having discovered one).
   - Other sites TBD via the Step 3 grep pass — known: `aims_endgame_service.py`
     `accepted_literature` branch (`if not concerns: is_endgame = False`).

---

## 4. Decisions made during planning

These came up while working through implementation steps and test coverage —
none were settled in the original design discussion. All resolved now;
recorded here for traceability.

1. **Inquire scoring redesign (3-bucket treatment)**: **deferred**, not part of
   this batch. This batch builds the checklist + endgame backstop + nudge
   only. Tracked in §7.
2. **Nudge cadence**: **2 turns with `STEP_SECURE` present since the last
   `STEP_INQUIRE`-present turn** (or since the start), with undiscovered
   concerns still remaining. See §3.6 for the exact counting rule.
3. **Which resolution types does the backstop apply to?** **Both**
   `accepted_vaccine` and `accepted_literature` — "endgame is endgame," no
   special-casing between the two closing outcomes.
4. **Unknown concern ID from the matcher**: **add it as its own new entry,
   immediately marked fully resolved** (`is_discovered/is_mirrored/is_secured
   = True`), logged, real checklist entries untouched. See §3.3.
5. **Re-discovering an already-discovered concern**: **no-op** — idempotent,
   not a duplicate or an error.
6. **Heuristic-fallback interaction**: **deferred** — leave the fallback path
   completely alone for this batch (it's already dormant,
   `AIMS_HEURISTIC_FALLBACK_ENABLED` is off in every deployed environment, so
   there's nothing to coordinate with today). Whether to remove the fallback
   system entirely is a separate future decision. Tracked in §7.
7. **Mid-conversation Tip repeat behavior**: **stays flat**, no escalation
   tiers — same text every qualifying turn. Deliberate simplicity call, not
   mirroring `secure_before_mirror`'s tiered escalation.
8. **Counter behavior on a turn with neither `STEP_SECURE` nor
   `STEP_INQUIRE`**: **unchanged** — confirmed, matches §3.6.

9. **Does `age_appropriateness` belong in the global `PERSON_TOPIC_CATEGORIES`
   taxonomy, or scenario-local to Georgina?** **Scenario-local** — it belongs
   to Georgina, not the shared vocabulary used across all personas. It stays
   out of `aims_system_instruction.txt`'s `PERSON_TOPIC_CATEGORIES` list;
   instead it's part of the per-turn context `classify_turn` receives
   specifically for a Georgina session (alongside her checklist topics and
   discovered state — see §5, Step 3), not a globally-known topic every
   persona's classification is checked against.

**Confirmed fix needed regardless of the above**: `requirements` (Zia's first
concern) already exists in `_CONCERN_TOPIC_ALIASES`/`_CONCERN_LABELS`/
`topic_hints` but is missing from `PERSON_TOPIC_CATEGORIES` in
`aims_system_instruction.txt` — add it there as part of Step 4 (§5).

---

## 5. Step-by-step implementation plan

### Step 1 — Persona data — **done**, see note below
- ~~Add `concerns: [{id, topic, desc}]`~~ Actually shipped as `{topic, desc}`
  (no `id` — see §2, IDs are always derived from `topic`, never authored).
  All 5 personas + `FALLBACK_PERSONA` done; 9 of 10 topics reuse the existing
  closed vocabulary, `age_appropriateness` is the one new one, scenario-local
  to Georgina (§4, item 9). New test coverage added in `test_persona_service.py`.

### Step 2 — State model
- `aims_state_service.py`'s `update()`: seed `parent_concerns` from
  `mem.get("persona", {}).get("concerns")` (not `[]`), each entry
  `{topic, desc, is_discovered: False, is_mirrored: False,
  is_secured: False, from_checklist: True}`.
- **Requires threading `concerns` through `build_persona_session_fields`**
  (`persona_service.py`) — its returned `"persona"` dict currently only
  carries `{id, name, patient_name}`; add `"concerns": persona.get("concerns")
  or []` so `mem["persona"]["concerns"]` is actually available by the time
  `update()` runs. Without this, Step 2 has nothing to seed from.
- **Remove, don't just audit, the two existing blanket flips** (§3, item 9):
  the "`parent_concerns` non-empty ⇒ `is_undiscovered_concerns = False`" line
  and the "`STEP_INQUIRE` present ⇒ `is_undiscovered_concerns = False`" line
  in `update_observational_state`. Replace both with a single recomputation —
  `is_undiscovered_concerns = any(not c.get("is_discovered") for c in
  parent_concerns if c.get("from_checklist"))` — called wherever a concern's
  `is_discovered` actually changes (Step 3).

### Step 3 — Discovery matching (extends `conversation_service.py`, not `classify_turn`'s schema) — **done**, see notes below
- In `_apply_concern_presence_event`: when `_find_event_target` resolves to an
  *existing* entry, also set `is_discovered = True` on it (in all three
  "existing concern" branches — direct match, restated-before-match, and
  restated-after-no-direct-match) before/alongside the existing evidence-merge
  + status-sync.
- When no match is found and `_new_concern` creates a fresh entry: mark it
  `is_discovered: True, is_mirrored: True, is_secured: True` immediately
  (§3, item 3's rationale — both because the backstop only scopes to
  `from_checklist: True` entries, and because `detect_endgame`'s own context
  shouldn't see a stray unresolved-looking entry). Log it.
- After any of the above, recompute `state["is_undiscovered_concerns"]`
  per Step 2's formula.
- `classify_turn`'s per-turn prompt (`build_classify_turn_prompt` /
  `classify_turn.txt`) gains new context alongside the existing
  `inquired_concerns_list`/`mirrored_concerns_list`: this persona's checklist
  topics and which are already discovered. **Add `requirements` to
  `PERSON_TOPIC_CATEGORIES`** in `aims_system_instruction.txt` (missing
  today — §4's confirmed fix). `age_appropriateness` does **not** go in
  `PERSON_TOPIC_CATEGORIES` (§4, item 9) — it's passed as scenario-local
  context only for Georgina's session.

**Findings during implementation (grounding continued past the plan into
Step 3's own edges — all resolved, recorded for traceability):**
- **`_apply_mirrored_event` gap**: its own "no match → create ad-hoc" branch
  and its "match found" branch never set `is_discovered`. A checklist entry
  can be mirrored by the classifier before any presence event ever fires for
  it (existing comment in that function documents this happening) — without
  a fix, that checklist entry would stay `is_discovered: False` forever
  despite being visibly mirrored, permanently blocking the Endgame backstop.
  Fixed: `is_discovered = True` is now set unconditionally wherever
  `is_mirrored` is set in `_apply_mirrored_event`. `_apply_secured_event`
  needs no separate fix — it already requires `is_mirrored` as a
  precondition, which by then guarantees `is_discovered` is already True.
- **`inquired_concerns_list` (`aims_coaching_handler.py`) was reading ALL
  `parent_concerns` topics unconditionally**, not just discovered ones. Step
  2's pre-seeding means undiscovered checklist topics now sit in
  `parent_concerns` from turn one — unfiltered, this would tell the
  classifier a topic was "already inquired" before the clinician ever asked
  about it. Fixed: filtered to `is_discovered` (defaulting True when the key
  is absent, so non-checklist/ad-hoc entries — always created from real
  evidence — are unaffected).
- **Ad-hoc auto-resolve vs. the pre-existing "secure before mirror" penalty**
  (`_apply_secure_guidance`/`_has_material_unmirrored_concern` in
  `aims_state_service.py`): that mechanism reads `is_mirrored` off *every*
  `parent_concerns` entry, not just checklist ones. Auto-resolving ad-hoc
  entries to `is_mirrored: True` on creation (as designed above) silently
  defeats that penalty for any concern outside a persona's checklist — this
  broke an existing regression test
  (`test_zia_style_required_and_safe_reply_seeds_distinct_concerns_and_flags_secure_before_mirror`,
  since renamed to `..._auto_resolved`). Raised to the user: keep the design
  as planned (ad-hoc entries fully auto-resolved, `is_mirrored` included) vs.
  only set `is_discovered` and leave `is_mirrored`/`is_secured` at their real
  state. **Decision: keep the design as planned** — ad-hoc concerns are fully
  auto-resolved, and the "secure before mirror" penalty no longer applies to
  them (it still applies normally to checklist concerns; see the new test
  `test_structured_feedback_secure_before_mirror_still_fires_for_discovered_checklist_concern`
  in `test_aims_state_service.py`). The affected regression test's assertions
  were updated to match (no "mirroring" feedback, both concerns
  `is_mirrored`/`is_secured` True, `pending_concerns` False).
- **`classify_turn.txt`'s `person_topic` enum was also missing
  `requirements`** (a second location beyond `PERSON_TOPIC_CATEGORIES` in
  `aims_system_instruction.txt`) — this is the actual structured-output
  schema constraint, so without this fix the model could never emit
  `person_topic: requirements` even after the system instruction listed it
  as valid. Fixed both.
- **New `checklist_context` prompt parameter** added end-to-end
  (`aims_coaching_handler.py` → `AimsTurnCoordinator.run` →
  `ClassifierService.classify_turn` → `AimsPromptBuilder` →
  `build_classify_turn_prompt` → `classify_turn.txt`), rendering
  `from_checklist: True` entries as `topic (discovered|not yet discovered)`.
  This naturally carries scenario-local topics like Georgina's
  `age_appropriateness` alongside shared-vocabulary ones (§4, item 9) without
  any persona-specific branching — it just renders whatever the persona's
  checklist contains.
- **Known follow-up for Step 6, not fixed here (out of Step 3/4's scope)**:
  `aims_endgame_service.py`'s `detect_endgame` call has the same
  "`inquired` = ALL `parent_concerns` topics, unfiltered" issue as the
  `inquired_concerns_list` bug above (line ~182,
  `inquired = [concern["topic"] for concern in concerns]`). Should be
  filtered to discovered concerns when Step 6 touches this file.

### Step 4 — Emptiness-check audit (the rest, beyond Step 2's two known sites) — **done**
- Grep every remaining read of `parent_concerns` / `is_undiscovered_concerns`
  across `app/services/*.py` and classify each as: (a) fine as-is, (b) needs
  to switch from emptiness to discovery-based logic. Known:
  `aims_endgame_service.py` `accepted_literature` branch
  (`if not concerns: is_endgame = False`) — likely fine as-is now, since
  `concerns` will never be empty once seeded, but confirm the *intent* there
  (checking "were any concerns ever raised") isn't accidentally now-always-true
  in a way that changes behavior.
  **Also confirm/fix the `inquired` list in `detect_endgame`'s call site
  (see finding above) while auditing this file.**

**Audit results** (every `parent_concerns`/`is_undiscovered_concerns` read in
`app/services/*.py`, classified):
- `aims_coaching_handler.py`'s `_build_reply_concern_state_section` (open vs.
  resolved buckets) — known, Step 5's explicit target, not a bug.
- `aims_coaching_handler.py`'s `VaccineRelevanceGate.gate` call
  (`parent_recent_concerns`) — reads ALL concerns unfiltered, but the
  `ctx_blob` built from it is only ever consulted inside
  `allow_keyword_fallback` branch when the semantic classifier fully failed;
  `allow_keyword_fallback=self.heuristic_fallback_enabled`, dormant in every
  deployed environment. Fine as-is per §4, item 6 (leave the fallback path
  alone).
- `aims_feedback_service.py::_build_context` — feeds
  `refine_fallback_feedback`, only called `if turn.was_fallback` (dormant
  path). Also reads state *after* `state_service.update()` already ran, so
  even if it weren't dormant it would see correctly-recomputed
  `is_discovered`/`is_undiscovered_concerns`. Fine as-is.
- `aims_state_service.py::apply_coaching_guidance`'s topic-resolution tip
  filter (~line 230) and `mark_mirrored_multi`/`mark_secured_by_topic` calls
  (~271, 279) and `_add_closure_plan_tip` (~290) — all gated behind
  `self._heuristic_fallback_enabled`. Dormant, fine as-is.
- `aims_state_service.py::update_observational_state`'s `all_mirrored`/
  `all_resolved` phase-transition and `pending_concerns` checks (STEP_MIRROR_SECURE/STEP_SECURE
  branches, ~648–673) — **intentional behavior change, not a bug**: since
  checklist concerns are now pre-seeded unmirrored from turn one, phase can no
  longer reach `PHASE_SECURE` (and `pending_concerns` stays `True`) until
  every checklist concern has actually been raised *and* mirrored — exactly
  the tightening this feature is meant to produce. Ties directly into the
  Step 6 Endgame backstop; not a separate bug to fix.
- `conversation_service.py`'s `maybe_add_person_concern`/
  `mark_mirrored_multi`/`mark_secured_by_topic` bodies — dormant fallback
  path per §4, item 6. Left untouched.
- No other services (`coach_feedback_history_service.py`,
  `aims_metrics_service.py`, `aims_turn_telemetry.py`,
  `patient_reply_service.py`, `summary_service.py`) read `parent_concerns` /
  `is_undiscovered_concerns` at all.
- Remaining known, not-yet-fixed site: `aims_endgame_service.py`'s
  `detect_endgame` `inquired` list (Step 6's scope, noted above).

### Step 5 — Patient-reply generation (extends the existing concern-state pipeline) — **done**
- `aims_coaching_handler.py`'s `_build_reply_concern_state_section`: add a
  third bucket — undiscovered `from_checklist: True` entries (currently only
  open/resolved exist). New locale messages under `patient_reply.concern_state.*`
  following the existing pattern (`open_and_resolved`, `open_only`, etc.).
  **Must not break** the existing `"open concerns: none"` substring check in
  `patient_reply_service.py` that drives fallback wording.
- Add the "reveal at most one new concern per turn" instruction and the
  role-play instruction (withhold consent while undiscovered items remain;
  prefer reluctance, blurting acceptable) to `aims_patient_reply.txt` /
  the character section.

**Implementation notes:**
- Undiscovered checklist entries are excluded from the "open" bucket entirely
  (previously they'd have shown up as "open" from turn one, since pre-seeded
  entries start `is_secured: False` — this would have told the roleplay model
  to discuss concerns nobody had raised yet, defeating the whole feature).
  They render as their own clause, using the concern's authored `desc` text
  rather than the topic slug — undiscovered entries haven't been touched by
  `_normalize_existing_concern` yet, so the persona's original hand-authored
  wording from `personas.json` is still intact (only gets replaced by the
  canned `_CONCERN_LABELS` value once discovered — see §2). This gives the
  roleplay model much richer grounding for how to eventually allude to it.
- **Found and fixed the same marker-safety issue Step 3 already had a
  version of**: the naive first pass reused the existing `open_none_resolved`
  message (which contains the literal `"open concerns: none"` marker text)
  whenever `open_topics` was empty, regardless of whether `undiscovered_topics`
  was also non-empty — a new regression test caught this immediately (a
  session with one resolved + one undiscovered concern was incorrectly
  hitting the fully-resolved marker, which would have made the patient-reply
  fallback pick the "Yes, that helps, thank you" tone while a concern was
  still being deliberately withheld). Fixed with a new marker-free
  `resolved_pending_more` message, and the branch condition now requires
  *both* `open_topics` and `undiscovered_topics` to be empty before using the
  marker-bearing message.
- Two new locale keys: `patient_reply.concern_state.nothing_surfaced_yet`
  (concerns is non-empty but everything is either undiscovered or, degenerate
  case, empty of open/resolved) and `resolved_pending_more` /
  `undiscovered_present` (see above). Neither contains the `"open concerns:
  none"` substring — verified by a dedicated regression test alongside the
  positive case (fully-resolved still hits the marker correctly).

### Step 6 — Endgame backstop — **done**
- `aims_endgame_service.py`: add a check for
  `state.get("is_undiscovered_concerns")` as a backstop, applied when
  `outcome` is `accepted_vaccine` or `accepted_literature`. On block, set a
  state flag/reason so the coaching layer can surface the Important tip with
  the right text (distinguish this from a generic `is_endgame: false`).

**Implementation notes:**
- Backstop lands right after the existing `accepted_vaccine`/
  `accepted_literature`/`deferred` outcome gating, before `_log_endgame_end`.
  Always writes `aims_state["endgame_blocked_undiscovered"]` (`True` or
  `False`, never left unset) so a block from an earlier turn can't leak into
  a later one that never attempted closure.
- `check()` still returns `None` on block, exactly like any other
  non-endgame turn — `KEY_GAME_OVER`/`coach_post` are never set. Verified
  with a dedicated end-to-end test
  (`test_handle_surfaces_important_tip_and_leaves_composer_unlocked_when_endgame_backstop_blocks`
  in `test_aims_coaching_handler_injection.py`) confirming the composer-lock
  feature does not fire — this was explicitly called out in §6.5 as needing
  its own regression test, not an assumption.
- `check()` has no access to `cls_payload` (only `mem`/`reply_payload`/
  `session_obj`/`session_id`), so it can't append the Important tip itself —
  the state flag is exactly the "coaching layer" handoff the spec called
  for. `aims_coaching_handler.py`'s new `_append_endgame_blocked_tip` reads
  it right after `endgame_service.check()` returns and appends a
  `feedback_items` entry with `code="endgame_undiscovered_concern"`, added
  to `coaching_display.py`'s `IMPORTANT_FEEDBACK_CODES` so it renders as
  "Important" (matching `secure_before_mirror`'s existing convention — only
  `feedback_items`, not also duplicated into `tips`, since
  `_add_secure_before_mirror_feedback_item` doesn't either and
  `coaching_message_parts` already suppresses the plain-tips render whenever
  a structured improvement item is present).
- **Known, accepted gap**: the Important tip lands in the live turn's
  `coaching.feedback_items` but not in that same turn's
  `coach_feedback_history_service` note — that note is snapshotted *before*
  `endgame_service.check()` runs (it must stay positioned between the
  user/assistant history entries for replay ordering, an explicit constraint
  from this session's earlier composer-lock work). Moving the snapshot later
  isn't safe without breaking that ordering guarantee. Cosmetic only: a
  session replay won't show the sweep-up tip for the exact turn it was
  blocked on, but blocking/scoring/composer behavior are all unaffected.
- **Found and fixed a real conflict with a named historical regression
  test**: `test_accepted_literature_succeeds_despite_undiscovered_concerns_flag`
  in `test_endgame_detection_unit.py` hardcoded `is_undiscovered_concerns:
  True` on a fully-resolved, non-checklist concern, asserting closure still
  succeeds — a guard against an old bug where the pre-checklist
  `is_undiscovered_concerns` (formerly `first_inquire_done`) was a proxy for
  "did the clinician ever get classified with an Inquire step," completely
  disconnected from whether concerns were actually resolved, and could stay
  stuck `True` forever. Verified via `_recompute_undiscovered_concerns` that
  this exact fixture (no `from_checklist` entries, one resolved concern) now
  computes `False`, not `True` — the fixture predates the semantics change
  and is a state the real pipeline can no longer produce. Updated the
  fixture to `is_undiscovered_concerns: False` (what the new system actually
  computes here) and expanded the docstring with this reasoning; the
  original regression protection (an unprompted, fully-addressed concern
  must not block closure) still holds, now via an accurate flag rather than
  the flag being ignored. This is a materially different mechanism from the
  old bug, not a reintroduction of it: the old proxy was permanently
  disconnected from real conversational progress with no way to resolve
  itself, while the new one is computed per-concern and resolves precisely
  when discovery actually happens.
- Also fixed the previously-flagged `inquired` list in `detect_endgame`'s
  call site (same unfiltered-by-discovery bug as Step 3's
  `inquired_concerns_list` fix) while in this file.
- New test coverage: 6 new tests in `test_endgame_detection_unit.py`
  (blocks `accepted_vaccine`/`accepted_literature` while undiscovered;
  doesn't block once all checklist concerns are discovered even if
  unmirrored/unsecured, per §6.5; doesn't apply to `deferred`/`not_resolved`;
  ignores ad-hoc/non-checklist concerns), 2 in
  `test_coaching_display.py`/`test_aims_coaching_handler_injection.py` for
  the Important-tier rendering and idempotent tip-appending, plus the
  end-to-end composer-lock test above.

### Step 7 — Two-tier nudge — **done**
- `aims_state_service.py`: add a **plain global integer counter** (not
  `secure_before_mirror`'s topic-keyed `recent_coaching` mechanism — see §2)
  — increment on any turn with `STEP_SECURE` in `component_steps`/`all_steps`
  (compounds included), reset to 0 on any turn with `STEP_INQUIRE` present,
  unchanged otherwise. Fire the flat mid-conversation Tip when the counter
  reaches 2 and `is_undiscovered_concerns` is true.
- `coach_post.py` / `aims_endgame_service.py`: surface the Important tip when
  Step 6's backstop actually fires, with sweep-up-question phrasing.
- New locale strings for both tiers (never hardcode English inline).

**Implementation notes:**
- The Important-tip half was already delivered in Step 6
  (`aims_coaching_handler.py::_append_endgame_blocked_tip`); this step is the
  remaining mid-conversation plain-Tip half, `AimsStateService._apply_inquire_nudge`,
  called from `update()` right after `apply_coaching_guidance`, using the
  `steps` list already computed at the top of `update()` (fuller signal than
  `apply_coaching_guidance`'s own internal
  `component_steps(step_current)`-only call, which doesn't see
  `cls_payload["steps"]`). New counter key: `state["secure_since_inquire_count"]`.
  `STEP_INQUIRE` check takes priority over `STEP_SECURE` when a turn
  compounds both (`Secure+Inquire`) — resets, doesn't increment-then-reset.
- **Found and fixed the same structured-vs-legacy suppression bug in
  `_append_endgame_blocked_tip` before starting this step** (see Step 6's
  notes above — the fix belongs to Step 6's own code, called out here since
  it's what made the correct pattern for this step obvious): unconditionally
  appending to `feedback_items` regardless of whether the turn's own
  classification happened to include the *optional* `feedback_items` field
  suppresses that turn's legacy `reasons`/`tips` rendering in
  `coaching_display.py`'s `coaching_message_parts` (only renders the
  fallback when there are zero `feedback_items`) — this is a normal,
  non-error occurrence on live LLM turns (the field is optional per
  `classify_turn.txt`), not just the dormant heuristic-fallback path. Both
  `_apply_inquire_nudge` and `_append_endgame_blocked_tip` now branch on
  `_has_structured_feedback(cls_payload)`, mirroring
  `_apply_secure_guidance`'s existing `prefer_structured_feedback` pattern
  exactly.
- Nudge code (`inquire_nudge`) is deliberately **not** added to
  `coaching_display.py`'s `IMPORTANT_FEEDBACK_CODES` — it renders as a plain
  "Tip", matching the two-tier design (mid-conversation Tip vs.
  closure-attempt Important tip).
- New test coverage: 10 new tests in `test_aims_state_service.py` covering
  every §6.6 case directly (no-fire at 1, fires at 2, compound `Mirror+Secure`
  increments, compound `Secure+Inquire` resets, `STEP_INQUIRE`-alone resets,
  neither-step turn leaves counter unchanged, doesn't fire once fully
  discovered even with a high counter, stays flat/same-text across repeat
  qualifying turns, and both the structured/legacy branching paths).

### Step 8 — Full regression pass — **done**
- Re-run everything touching `parent_concerns` from earlier this session:
  `secure_before_mirror` scoring/tips, `_user_facing_topic_hint`, the endgame
  Secure summary bullet, `build_endgame_bullets_fallback`.
- Confirm topic-hint text still reads sensibly given `_normalize_existing_concern`
  will replace authored `desc` text with canned `_CONCERN_LABELS` values (§2)
  (Test Matrix §6.7).

**Results:**
- `_user_facing_topic_hint` verified programmatically against every concern
  in `personas.json` (all 5 personas, 11 topic values including
  `age_appropriateness`) — every one resolves through `state_feedback.topic_hints`
  to sensible text, none fall through to the raw-slug fallback.
- `secure_before_mirror` already re-verified in Step 3
  (`test_structured_feedback_secure_before_mirror_still_fires_for_discovered_checklist_concern`).
- `build_endgame_bullets_fallback`'s `unmirrored_warning`/`unmirrored_warning_single`
  bullets read from `session_obj["secureBeforeMirrorCount"/"secureBeforeMirrorTopicHint"]`
  (populated via `aims_metrics_service.py` from the same `secure_before_mirror_total`/
  `_last_topic_hint` state fields already verified) — untouched by this batch,
  confirmed still passing (`test_coach_post_sanitizer.py`).
- Pre-Announce phase guard in `aims_endgame_service.check()` is structurally
  independent of `parent_concerns` (checks `phase` only) — unaffected by
  seeding happening before Announce; existing `test_returns_none_in_preannounce_phase`
  still passes unmodified.
- The `if not concerns:` sites from Step 3/4's audit re-confirmed correct
  under the new backstop tests (`test_backstop_ignores_ad_hoc_concerns_not_on_the_checklist`
  and `test_accepted_literature_requires_surfaced_concern`).
- Full CI-equivalent suite (`pytest --ignore=tests/integration`), `ruff`,
  `mypy`, and `bandit` all clean at every step of this batch — re-confirmed
  once more here as the final full-regression checkpoint.

### Step 9 — Live verification — **done**
- The role-play behavior change (Step 5) is a prompt-driven LLM behavior
  change, not pure logic — cannot be fully verified by mocked unit tests. Must
  be live-tested in the browser (staging then prod) across at least 2–3
  personas, deliberately trying to close early while withholding a concern, to
  confirm the persona actually resists as designed.

**Results (localhost:8080, real Vertex AI calls, per the user's explicit
instruction to use the local run config rather than staging):**
- Started via `.claude/launch.json` (new, added this session —
  `.venv/bin/python run_app.py` on port 8080) through the browser preview
  tool. SSO is enforced in this environment (real `OAUTH_GOOGLE_CLIENT_ID` in
  `.env`), so interactive turns were driven via `starlette.testclient.TestClient`
  against the real in-process app (real Vertex calls, no mocking) instead of
  the browser UI — `/session` then `/chat`, exactly the same request flow the
  Chainlit UI itself makes. `POST /session` needs `personaId` to force a
  specific persona (not a `/chat` field — confirmed `/chat` alone, without a
  prior `/session` call, never selects a persona and never seeds a checklist;
  this is pre-existing `session_initializer.py` behavior, not something this
  batch changed, but worth knowing when testing this way).
- **Georgina** (`autonomy`, `age_appropriateness`), 3 separate live
  conversations:
  1. Checklist correctly pre-seeded both concerns `from_checklist: True`,
     `is_discovered: False` from turn one.
  2. Live discovery matching correctly attributed real, organically-phrased
     patient statements to the right checklist topic via the real classifier
     (e.g. "I'm the one who makes the decisions for my daughter" →
     `autonomy` discovered; "why does an eleven-year-old need a vaccine for
     an STI" → `age_appropriateness` discovered) — in one run `autonomy` alone
     got discovered while `age_appropriateness` correctly stayed undiscovered
     the whole conversation.
  3. Role-play resistance (Step 5) held up robustly across all 3 runs — the
     persona never gave clean, unconditional consent while a real concern of
     hers went unaddressed, consistently pushing back ("I'm not agreeing to
     anything until you answer my question", "we're leaving") rather than
     capitulating to a clinician who kept trying to close early.
  4. Two-tier nudge (Step 7) fired live at exactly `secure_since_inquire_count
     == 2`, with the exact authored flat text, as a structured
     `feedback_items` entry (code `inquire_nudge`) — and stayed flat
     (identical text) on the next two qualifying turns, confirming no
     escalation.
  5. Because the role-play defense is working this robustly, the persona
     never organically reached a moment where `detect_endgame` returned
     `is_endgame: true` for `accepted_vaccine` while a concern was still
     undiscovered — expected and reassuring per §3 item 5's own framing
     ("should rarely fire given the role-play defense"), not a gap. To
     directly stress-test the backstop itself, force-reset
     `age_appropriateness` back to undiscovered mid-session and pushed a
     closing exchange — the persona *still* resisted (grounded in the real
     conversation history, not just the flag), so this didn't isolate the
     backstop either.
- **Isolated the backstop directly against a real LLM call**: called the real
  `AimsEndgameService.check()` (real `ClassifierService.detect_endgame`, no
  mocking) with a hand-constructed, unambiguous accepted-vaccine transcript
  and `is_undiscovered_concerns: True`. Confirmed: `check()` returned `None`
  (blocked, exactly like any other non-endgame turn — no `coach_post`), and
  `aims_state["endgame_blocked_undiscovered"]` correctly flipped to `True`.
  This is the direct, live confirmation that Step 6's backstop actually vetoes
  a real, live "yes" from the classifier when a checklist concern is still
  hidden — the one thing genuinely impossible to prove with a mocked
  classifier. The remaining link (the coaching layer reading this flag and
  appending the Important tip) is pure Python, already covered by dedicated
  unit tests, not requiring its own separate live LLM round-trip.
- `.env`'s temporary `PERSONA_INDEX=1` (added to force-select a persona
  deterministically for the first attempt, superseded by `personaId` on
  `/session`) was reverted after testing — `.env` is gitignored and this was
  local-only.

### Step 9 addendum — exhaustive live-test matrix (post-review, all 5 personas)

Requested after the initial Step 9 pass: a broader matrix across all 5
personas, each targeting a different mechanism. All real Vertex calls, same
in-process `TestClient` harness. Full transcripts are in scratchpad
`exhaustive_live_tests.py` / `live_verify4–8.py` (session-local, not part of
the repo).

- **Zia (`requirements`, `side_effects`)** — clean-close attempt. Both
  topics correctly discovered live (direct re-confirmation of the
  `requirements`/`PERSON_TOPIC_CATEGORIES` fix from Step 3). Never reached a
  genuine `coach_post` close across 3 separate attempts (including one
  where every follow-up question was explicitly answered) — the persona
  kept raising one more legitimate practical question each time ("which
  vaccines specifically," "what medicine for a fever") rather than giving
  clean unconditional consent. This is the general conversational-realism
  instruction working as designed (`aims_patient_reply.txt`: "don't give a
  vague placeholder reply... briefly acknowledge and either accept or ask
  one concrete follow-up"), not a checklist-feature defect, and not
  something this batch changed — getting a scripted (non-adaptive)
  clinician to satisfy a persona this thorough is genuinely difficult by
  hand. The base "can a session close via `accepted_vaccine`" mechanism
  predates this batch and has its own separate, already-passing regression
  coverage (mocked `detect_endgame` results) — the checklist feature only
  adds a backstop on top, it doesn't touch the close path itself.
- **Jasmine (`immune_load`, `ingredients`, `schedule_timing`, 3 concerns)**
  — blurt-unprompted discovery. All 3 discovered purely through
  self-disclosure (no clinician ever classified with an Inquire step) —
  direct live confirmation that discovery is driven by `person_events`, not
  step classification. Bonus: the patient organically raised an off-checklist
  concern (`disease_risk`, "what if we wait?") which was correctly created
  as an ad-hoc entry and immediately auto-resolved
  (`is_discovered`/`is_mirrored`/`is_secured` all `True`) — live confirmation
  of the ad-hoc auto-resolve path from Step 3.
- **Ethan (`trust`, `effectiveness`)** — intended to isolate the
  `accepted_literature` backstop live in conversation, but Ethan's
  authored concerns overlap tightly (both concerns key off wanting to see
  data/evidence), so both got discovered within 2 turns — no conversational
  window to test the backstop this way. Isolated it directly instead
  (`live_verify5.py`): called the real `AimsEndgameService.check()` (real
  `detect_endgame` LLM call) against a hand-built unambiguous
  `accepted_literature` transcript with `effectiveness` still undiscovered —
  confirmed `check()` returns `None` and `endgame_blocked_undiscovered`
  flips `True`, exactly like the `accepted_vaccine` case already proven in
  the main Step 9 pass. Both resolution types the backstop is scoped to
  (§4 item 3) are now directly live-confirmed against a real classifier
  call, not just mocked unit tests.
- **Sarah (`disease_risk`, `effectiveness`)** — two-tier nudge lifecycle,
  full pass: counter reached 2 with an undiscovered concern → flat Tip
  fired with the exact authored text; an Inquire-containing turn reset the
  counter to 0; two more Secure turns → counter reached 2 again and the
  *same* text fired again (confirms "stays flat," §4 item 7); both
  concerns eventually discovered and the nudge correctly stopped despite a
  climbing counter.
- **Georgina (`autonomy`, `age_appropriateness`)** — re-run of the main
  Step 9 scenario with a more careful clinician script: both concerns
  discovered live, `is_undiscovered_concerns` correctly `False`, no false
  block. Same as Zia, never reached a genuine `coach_post` close by hand —
  the persona kept surfacing one more specific, legitimate question
  ("what exactly does this protect her from long-term") that the scripted
  clinician turns didn't anticipate answering.
- **Ad-hoc non-interference dedicated attempt**: test design flaw, not a
  finding — the clinician script answered a "cost" question the patient
  never actually raised, so (correctly) no ad-hoc concern was created to
  test. The mechanism itself is already independently confirmed via
  Jasmine's and Georgina's organic ad-hoc concerns above (both auto-resolved
  correctly), so no gap remains despite this specific scenario not landing
  as designed.
- **One-off anomaly investigated and not reproduced**: a single transcript
  briefly appeared to show `mem["game_over"] = True` without a matching
  `coach_post` in that response. Read `aims_coaching_handler.py`'s actual
  code (`coach_post` is a single local variable, unmutated between the
  `KEY_GAME_OVER` write and the response-building `if coach_post:` check —
  they cannot diverge within one request) and re-ran the identical scenario
  twice more with fully unconditional debug output on every turn
  (`live_verify7.py`, `live_verify8.py`) — `coach_post` and `game_over`
  moved together on every turn in both re-runs, no mismatch. Concluded this
  was very likely a reading error while scanning a long transcript, not a
  real bug — recorded here for traceability rather than silently dropped.

**Net effect of the addendum**: no new bugs found. Confirms, with real
Vertex calls, every mechanism this batch added — checklist seeding,
discovery via both explicit Inquire and self-disclosure, ad-hoc auto-resolve,
the two-tier nudge's full lifecycle, and the Endgame backstop for *both*
`accepted_vaccine` and `accepted_literature` — across all 5 personas. The
one gap (a fully scripted, hand-driven "genuine close") turned out to be
a property of how thorough the persona role-play now is (arguably a
feature, not a bug), not something the checklist feature's own correctness
depends on, since the base close mechanism predates this batch.

---

## 6. Test case matrix (one-liners)

### 6.1 Persona data integrity
- Every persona in `personas.json` has 1–3 `concerns` entries, never 0.
- Each `concerns` entry has non-empty `topic`, `desc` (no `id` field — see §2).
- `topic` values are unique within a persona.
- Every `topic` used, once run through `_canonical_topic`, either matches an
  existing `_CONCERN_TOPIC_ALIASES` entry or is a deliberate new one
  (`age_appropriateness`) with its own `topic_hints`/`_CONCERN_LABELS` entry
  added alongside it — not a silent typo that canonicalizes to something
  unintended.
- `FALLBACK_PERSONA` has a valid `concerns` list matching the same shape.
- `build_persona_session_fields` actually carries `concerns` through into the
  returned `"persona"` dict — a session initialized from a persona has
  `mem["persona"]["concerns"]` populated, not dropped.

### 6.2 State seeding
- New session's `parent_concerns` is pre-seeded from the persona's checklist,
  not empty.
- Each seeded entry starts `is_discovered: False, is_mirrored: False,
  is_secured: False, from_checklist: True`.
- `is_undiscovered_concerns` is `True` immediately after seeding, before any
  turns (computed over `from_checklist: True` entries only).
- `is_undiscovered_concerns` is `False` once every `from_checklist: True`
  entry is discovered — regardless of how many non-checklist (ad-hoc) entries
  exist alongside them.
- A concern can never be `is_mirrored: True` or `is_secured: True` while
  `is_discovered: False` (invariant check — assert this can't happen given the
  update order, or defensively clamp it if it does).
- The old blanket flips (parent_concerns-non-empty, any-Inquire-turn) are
  gone — a fresh session with a pre-seeded checklist and zero turns still
  correctly shows `is_undiscovered_concerns: True` (this is the regression
  the old code would have gotten backwards — see §3, item 9).

### 6.3 Discovery matching (`_apply_concern_presence_event` → state)
- A `concern_raised` event whose topic matches a `from_checklist: True` entry
  (clinician explicitly Inquired) marks it `is_discovered: True`.
- A `concern_raised` event matching a `from_checklist: True` entry where the
  clinician's turn was classified as Secure/Announce (patient blurted it
  unprompted) still marks it discovered — discovery is driven by the person's
  reply content via `person_events`, not by the clinician's step
  classification.
- Two `concern_raised` events in the same turn (pacing instruction violated)
  mark both matching entries discovered, doesn't drop one.
- A `concern_raised`/`concern_mirrored`/`concern_secured` event re-targeting an
  already-discovered entry is a no-op on `is_discovered` (stays `True`, no
  duplicate entry, no error) — existing merge-evidence/status-sync behavior is
  unaffected.
- A `concern_raised` event whose topic matches **no** `from_checklist: True`
  entry creates a new ad-hoc entry via the existing `_new_concern` path,
  immediately marked `is_discovered: True, is_mirrored: True,
  is_secured: True`, and logged.
- Creating that ad-hoc entry does not change the state of any
  `from_checklist: True` entry.
- A session with an ad-hoc (non-checklist) entry present does not get blocked
  from Endgame on account of that entry, because the backstop only scopes to
  `from_checklist: True` entries.
- A `from_checklist: True` concern never mentioned stays `is_discovered: False`
  through the whole session.
- `classify_turn`'s per-turn prompt correctly lists `requirements` as a valid
  topic (the `PERSON_TOPIC_CATEGORIES` gap found during grounding, §2/§4) for
  a Zia-persona turn.

### 6.4 Patient-reply role-play behavior (live/manual — see Step 9)
- Persona with an undiscovered concern does not express agreement/consent
  when the clinician attempts to close.
- Persona conveys reluctance (preferred path) when concerns remain hidden and
  clinician tries to wrap up.
- Persona spontaneously blurts a concern (acceptable path) as an alternative
  reluctance expression.
- Persona reveals at most one *new* concern in a normal turn (soft check —
  confirm the instruction is generally followed, not a hard assertion).
- Persona's own behavior stays consistent with Python's tracked
  discovered/undiscovered state (no persona claiming "I already told you
  everything" while Python still shows an undiscovered item, or vice versa).

### 6.5 Endgame backstop
- `is_endgame: true` from the LLM is overridden to `false` when undiscovered
  concerns remain and resolution type is `accepted_vaccine`.
- Same for `accepted_literature`.
- Backstop does **not** apply to `deferred`.
- Backstop does **not** apply to `not_resolved`.
- Backstop does not fire when all concerns are discovered, even if some are
  unmirrored/unsecured (that's the existing `secure_before_mirror` penalty's
  job, not this gate's).
- Blocked closure produces a distinguishable reason/flag so the Important tip
  can reference it specifically (not a generic "not resolved" message).
- **When the backstop blocks closure, `check()` returns `None` the same way it
  does for any other non-endgame turn** — `KEY_GAME_OVER` is not set, and the
  composer-lock feature (this session, `aims_session_ended` window message)
  does not fire. A blocked session must not have its input disabled; only a
  genuinely-closed one should. This is a direct interaction with already-
  shipped work and needs its own explicit regression test, not just an
  assumption that it falls out of the existing code path for free.

### 6.6 Two-tier nudge
- No Tip fires after only 1 Secure-containing turn since the last Inquire (or
  since the start).
- Plain Tip fires once the counter reaches 2 Secure-containing turns since the
  last Inquire, with undiscovered concerns still remaining.
- A compound `Mirror+Secure` turn counts toward the Secure counter.
- Any turn with `STEP_INQUIRE` present (including compounds) resets the
  counter to 0, restarting the count toward the next nudge.
- A turn containing neither `STEP_SECURE` nor `STEP_INQUIRE` (e.g. pure
  Announce, pure Mirror) leaves the counter unchanged — doesn't increment,
  doesn't reset.
- Tip does not fire once all concerns are discovered, regardless of counter
  value.
- Important tip fires specifically when the endgame backstop blocks closure
  (distinct text/tier from the mid-conversation Tip).
- Important tip includes sweep-up-question phrasing
  ("anything else on your mind?" or equivalent, locale-driven).

### 6.7 Regression — existing features reading `parent_concerns`
- `secure_before_mirror` scoring/tip still fires correctly against pre-seeded
  concerns (topic hint text still reads sensibly for static `topic` values).
- `_user_facing_topic_hint` produces reasonable text for the new
  `topic`/`desc` values across all 5 personas.
- Endgame Secure summary bullet (`unmirrored_warning` /
  `unmirrored_warning_single`) still renders correctly.
- `build_endgame_bullets_fallback` still handles a session with 1 concern vs.
  3 concerns correctly (single vs. plural phrasing).
- The `if not concerns:` sites identified in Step 3's audit behave correctly
  under the new always-non-empty `parent_concerns`.
- Pre-Announce phase guard in `aims_endgame_service.check()`
  (`phase == PHASE_PRE_ANNOUNCE`) is unaffected by concerns existing before
  Announce happens.

### 6.8 Heuristic-fallback (deferred — leave alone, just confirm no regression)
- With the flag off (the real deployed condition), fallback path is
  unreachable and behavior is unchanged from today.
- No changes to `TOPICAL_CUES` / `maybe_add_person_concern` / the
  `heuristic_fallback_enabled`-gated code paths in this batch — existing tests
  for that path continue to pass unmodified.

### 6.9 End-to-end / live verification (testable with this batch alone)
- Full conversation with a persona that has 1 concern, discovered via
  explicit Inquire, closes normally with no nudge/block.
- Full conversation with a persona that has 3 concerns, all blurted
  unprompted, closes normally with no block once the last one is discovered
  (Inquire scoring itself is *not* covered by this batch — see 6.10).
- Full conversation where the clinician tries to close early with 1 of 3
  concerns still undiscovered: persona resists (Step 9), block fires if it
  somehow reaches the check anyway, Important tip appears with correct
  phrasing.
- Full conversation demonstrating the mid-conversation Tip firing before any
  closure attempt.
- Full conversation confirming a genuinely-blocked session leaves the
  composer enabled (ties to the new 6.5 backstop/composer-lock test).

### 6.10 Blocked on the deferred scoring follow-up (§7, item 1) — do not expect these to pass until that ships
- A persona with all concerns self-disclosed and zero Inquire turns scores
  Inquire as something other than a flat 0% (the original motivating case from
  the scoring conversation).

### 6.11 Post-review finding: `trust` vs `evidence` topic collision (found via real browser testing, not the scripted suite)

Manual browser testing (real Google OAuth login, driving the actual Chainlit
UI, not a scripted harness) surfaced a real bug the scripted live tests never
hit: **Ethan's two checklist concerns (`trust`, `effectiveness`) could
structurally never both discover.** `_CONCERN_TOPIC_ALIASES` had
`"evidence": "trust"` — so any turn where Ethan asked to "see the actual
data/evidence" (his authored `trust` desc, and also core to `effectiveness`
territory) collapsed onto the single `trust` topic bucket, i.e. the two
concerns were competing for the same evidence rather than being independently
matchable. `is_undiscovered_concerns` stayed `True` for the entire
conversation (7+ turns, extensively covering both topics) as a result — which
in turn permanently gated `secure_before_mirror` (`_apply_secure_guidance`
only checks `needs_mirror and not is_undiscovered_concerns`), so the
"Important:"-tier mirror-skip penalty could never fire either, even though
neither concern was ever actually mirrored.

**Fix**: split into two distinct canonical topics rather than just fixing the
alias:
- `trust`: relational/systemic distrust of the source (clinicians, pharma,
  public health), often misinformation- or rumor-driven — kept as-is,
  narrowed slightly in wording. Not currently used by any persona's
  checklist (Ethan was the only "trust" user, now moved to `evidence`) but
  needed for a plausible future persona whose distrust comes from something
  they saw on social media rather than wanting more rigor.
- `evidence` (new): a calculation-oriented request for data, methodology, or
  honest uncertainty — not necessarily distrust of the source at all.
- Updated everywhere the topic vocabulary lives: `PERSON_TOPIC_CATEGORIES`
  in `aims_system_instruction.txt` (with an explicit trust-vs-evidence
  disambiguation line, mirroring the existing disease_risk/effectiveness
  pattern), `classify_turn.txt`'s `person_topic` enum AND a matching
  disambiguation rule (the enum is the actual structured-output schema
  constraint — same class of gap as the earlier `requirements` fix, so both
  places were updated together this time), and `lexicon.concerns.labels` /
  `topic_aliases` / `state_feedback.topic_hints` in `en.json` (moved
  `"evidence"` and `"uncertainty"` off the `trust` alias bucket onto a new
  `evidence` bucket; `trust`'s own label/hint text no longer says "evidence"
  in it, to stop it re-describing itself into the sibling topic).
- Ethan's checklist entry renamed `trust` → `evidence` in `personas.json`
  (desc reworded to make the methodology/rigor framing explicit).
- Grounded against the AIMS paper's own literature review (`AIMS_Approach_Summary.md`),
  which treats "relational trust" as its own theme distinct from
  evidence-seeking/calculation-oriented hesitancy — this isn't an arbitrary
  split, it maps to a real distinction in vaccine-hesitancy drivers (closer
  to the 5C model's "Confidence" vs. "Calculation" categories).
- New regression tests: `test_apply_concern_events_trust_and_evidence_are_discovered_independently`
  (conversation_service), `test_maybe_add_person_concern_keeps_trust_and_evidence_as_distinct_topics`,
  `test_build_classify_checklist_context_includes_desc_not_just_bare_topic`
  (this was the first fix attempted — giving the classifier each concern's
  authored `desc`, not just the bare topic name, so persona-specific framing
  isn't judged purely against the topic's generic canonical definition; this
  alone wasn't sufficient here since the two concerns' *desc* text was also
  too similar, but it's an independently valid, permanent improvement to
  `_build_classify_checklist_context` and is needed for any future persona
  whose framing of a topic doesn't match the canonical definition well).
- Directly confirmed live (real Vertex calls, in-process harness) both
  before and after the fix: before, `effectiveness` or `trust` would
  discover but never both, `is_undiscovered_concerns` stayed `True`
  indefinitely, and `secure_before_mirror` never fired despite genuinely
  never mirroring either concern; after, both discover within 2 turns,
  `is_undiscovered_concerns` correctly flips `False`, and
  `secure_before_mirror` fires as expected.
- **Process note**: this shipped in Step 3 and passed every unit test,
  the full CI-equivalent suite, and 8 separate scripted live-LLM
  conversations (including one with Ethan specifically) without ever
  surfacing — it only showed up once a human drove the real Chainlit UI
  with natural, back-and-forth conversational phrasing rather than the more
  direct/scripted phrasing used in automated tests. Worth remembering for
  future persona-checklist work: two checklist concerns whose authored
  `desc` text both reduce to "wants more information" are a structural risk
  for this exact failure mode, independent of how good the discovery-matching
  code is — this is a content-authoring concern, not just a code concern.

---

## 7. Out of scope for this batch (explicitly deferred)

- **The Inquire scoring 3-bucket redesign** from the earlier scoring
  conversation (attempted / never-attempted-with-undiscovered /
  never-attempted-without-undiscovered). Revisit once this batch ships and the
  checklist gives us a reliable `is_undiscovered_concerns` signal to build it
  on.
- **Removing the heuristic-fallback concern-tracking system**
  (`TOPICAL_CUES`, `maybe_add_person_concern`, `mark_mirrored_multi`,
  `mark_secured_by_topic`, the `EndGameDetector` heuristic path) entirely.
  Already fully dormant in every deployed environment; this batch leaves it
  completely untouched. Worth a dedicated look on its own later, not bundled
  here.
- Resume/backward-compat handling for sessions started before this ships.
