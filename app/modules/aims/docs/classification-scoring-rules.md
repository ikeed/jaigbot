# AIMS Classification, Scoring, and Endgame Rules

This document is the canonical reference for how the AIMSBot system classifies, scores, and
coaches each clinician turn in an AIMS vaccine counselling session.  It reflects the current
implementation; all prompt text, deterministic overrides, and phase-state logic described here
are authoritative.

---

## 1. Overview

Every clinician turn is passed through a two-layer pipeline:

1. **LLM classifier** (`aims_system_instruction.txt` + `classify_turn.txt` → Gemini) — identifies the AIMS step(s),
   scores execution quality, and detects vaccine relevance and small talk.
2. **Deterministic post-processors** (Python) — apply hard-coded guards that fix known LLM
   failure modes and enforce structural AIMS rules that are categorical rather than linguistic.

The result of both layers is merged into a single `ClassifierResult` that drives coaching
feedback, phase-state tracking, and endgame detection.

Runtime ownership is split across injectable services:
- `AimsCoachingHandler` assembles the turn response and coordinates injected collaborators.
- `AimsTurnCoordinator` runs classification and patient-reply generation in parallel and applies
  deterministic classification fallback on timeout/failure.
- `AimsFeedbackService` may rewrite only the fallback coaching text for fallback turns; scoring
  and step detection remain deterministic.
- `AimsStateService` owns phase transitions, concern state, and stateful coaching guidance.
- `AimsMetricsService` owns per-session metrics.
- `CoachFeedbackHistoryService` owns compact coach-note history entries and public reason filtering.
- `AimsEndgameService` owns endgame hard guards, LLM/heuristic detection, and final coach posts.
- `aims_dependencies.py` contains the constructor-injected Protocol contracts.

---

## 2. AIMS Steps and Scoring Rubrics

Scores are integers 0–3.  The general principle: **3 = full execution**, **2 = decent but
incomplete**, **1 = notable flaw or missed element**, **0 = not a real AIMS turn**.

### 2.1 Announce

The first (and only) introduction or recommendation of vaccines.

| Score | Criteria |
|-------|----------|
| 3 | Presumptive recommendation + brief rationale + dialogue invite. e.g. *"It's time for Emily's MMR today — it protects against a very contagious virus. How does that sound?"* |
| 2 | Clear recommendation but missing rationale OR missing dialogue invite. |
| 1 | Soft or indirect introduction with no presumptive phrasing. e.g. *"One thing I like to talk about is vaccines…"* |

**Notes**
- A trailing *status question* ("Can I ask what her vaccination status is?") after a vaccine
  introduction stays as Announce, not Inquire.
- Announce fires exactly once per session.  The phase guard reclassifies any duplicate Announce
  based on message content (see §4.1).

---

### 2.2 Announce+Inquire *(compound step)*

A compound turn: first vaccine introduction (Announce) immediately followed by an open concern-surfacing question (Inquire) in the same turn. Normalised from the LLM's `steps: ["Announce", "Inquire"]` output.

| Score | Criteria |
|-------|----------|
| 3 | Presumptive recommendation + brief rationale + strong open question about concerns. e.g. *"It's time for Emily's MMR — it protects against a very contagious virus. What are your thoughts about vaccines?"* |
| 2 | Clear recommendation + open question, but missing rationale or question is slightly leading. |
| 1 | Soft introduction + closed/leading question, or the question is about status rather than concerns. |

**Notes**
- A trailing *status question* ("Can I ask about vaccination status?") stays as plain Announce, NOT Announce+Inquire.
- Announce+Inquire fires at most once (Announce is a one-time event). If Announce has already occurred and the classifier returns Announce+Inquire, the phase guard reclassifies based on message content (typically Inquire).
- **Phase**: Inquire dominates → phase advances to `InquireMirror`. Both Announce and Inquire are counted in session metrics.

---

### 2.3 Inquire

An open question to surface the person's *concerns or hesitancy* (must follow Announce).

| Score | Criteria |
|-------|----------|
| 3 | Single, open, neutral, non-leading question that invites full elaboration. e.g. *"What are your thoughts about the MMR?"* |
| 2 | Open and decent but stacked questions or slightly leading. |
| 1 | Closed question, "why" framing (feels accusatory), or leading phrasing. |

**Notes**
- Questions about vaccination *status or history* belong to Announce, not Inquire.
- Inquire is about *feelings and worries*, not logistics.

---

### 2.4 Mirror

Reflect the person's concern so they "feel felt" (must follow Inquire).  Mirror can reference
concerns raised anywhere in the conversation, not just the last message.

| Score | Criteria |
|-------|----------|
| 3 | Accurate reflection (explicit stem OR clear semantic restatement) + accuracy check. e.g. *"You want to be sure we're not overwhelming her tiny body — am I reading that right?"* |
| 2 | Decent reflection that captures the core concern without a direct rebuttal, but no accuracy check.  **Semantic mirroring** (restating the concern in the clinician's own words without formulaic stems) qualifies for Score 2. |
| 1 | Contains a direct **same-sentence** "but" pivot that immediately contradicts the reflected concern (e.g. *"I hear you, but actually the data shows…"*). |

**Important nuances**
- Score 1 applies **only** when "but" appears in the *same clause* as the reflection and negates
  it.  "But" appearing in a separate educational sentence later in the message does **not**
  trigger the penalty.
- Common explicit stems: *"It sounds like…"*, *"What I'm hearing is…"*, *"You're worried that…"*,
  *"I'm hearing that…"*
- **Semantic mirroring** (no explicit stem): restating the concern in the clinician's own words,
  validating the emotional core = valid Mirror, score 2 if no accuracy check.
- **Cognitive mirroring**: affirming the person's *reasoning* about a concern they've expressed =
  Mirror.  Validating a mere statement or preference (not a concern) = acknowledgment only →
  suggest Inquire.
- **Empathic normalization**: telling the person their reaction is normal or shared by others
  (*"most parents in your position feel the same way"*, *"it makes sense that your guard would go
  up"*) = Mirror when it validates a specific expressed concern.  This is a common clinician-style
  reflection that does NOT use formulaic stems.

---

### 2.5 Mirror+Inquire

A compound turn: brief reflection of the concern immediately followed by an open question.
Normalised from the LLM's `steps: ["Mirror", "Inquire"]` output.

| Score | Criteria |
|-------|----------|
| 3 | Accurate reflection + accuracy check + strong open question. |
| 2 | Decent reflection (no accuracy check) + decent open question. |
| 1 | Weak mirror component (same-sentence rebuttal) OR closed/leading question. |

---

### 2.6 Secure+Inquire *(compound step)*

A compound turn: autonomy-supportive securing of an addressed concern followed by an open question to surface additional concerns. Valid after Mirror when the clinician closes one loop and re-opens the floor. Normalised from `steps: ["Secure", "Inquire"]`.

| Score | Criteria |
|-------|----------|
| 3 | Explicit autonomy support + one tailored fact + safety-net OR follow-up plan + strong open question for more concerns. |
| 2 | Decent Secure component + decent Inquire question; may be missing one Secure element. |
| 1 | Either component weak (lecture without autonomy, or closed question). |

**Phase**: Inquire dominates → phase stays `InquireMirror`. Expands into both Secure and Inquire in session metrics.

---

### 2.7 Mirror+Secure *(compound step)*

A compound turn: accurate reflection of the expressed concern followed by autonomy-supportive
education, in the same turn.  Use when rapport is established and the clinician naturally blends
validation with tailored information.  Normalised from `steps: ["Mirror", "Secure"]`.

| Score | Criteria |
|-------|----------|
| 3 | Clear semantic mirror of the concern (parent "feels felt") + accuracy check + explicit autonomy affirmation + one tailored fact linked to the stated concern. |
| 2 | Decent mirror (concern addressed, no explicit accuracy check) + reasonable autonomy support + tailored education.  **This is the expected score for well-executed blended turns.** |
| 1 | Mirror component is vague or absent (effectively just Secure); OR direct "but" rebuttal in the same clause as the reflective opening. |

**Important nuances**
- The "but" penalty does **not** apply to the educational component — the education IS the Secure
  content, not a rebuttal.
- Dependency: Mirror+Secure requires a prior expressed concern (Inquired) to reflect.  Without a
  clear prior concern, classify as Secure only.
- Mirror+Secure is exempt from the pseudo-Secure penalty.

---

### 2.8 Mirror+Secure+Inquire *(compound step)*

A compound turn: reflection of an expressed concern, autonomy-supportive education, and an open
question to surface additional concerns in one turn. Normalised from
`steps: ["Mirror", "Secure", "Inquire"]`.

| Score | Criteria |
|-------|----------|
| 3 | Strong Mirror + strong Secure + strong open question for additional concerns. |
| 2 | Decent execution of all three components, but one component is incomplete. |
| 1 | One or more components are weak enough that the turn is mostly education, mostly inquiry, or contains a same-clause rebuttal of the reflection. |

**Phase**: Inquire dominates immediately, but if the turn resolves all tracked concerns, the
global reconciliation can advance phase to `Secure`. Expands into Mirror, Secure, and Inquire in
session metrics.

---

### 2.9 Secure

Done ONLY after Mirroring: affirm autonomy, offer ONE tailored fact, provide a safety-net.
Secure is about the relationship, not persuasion.

| Score | Criteria |
|-------|----------|
| 3 | Explicit autonomy affirmation (*"It's your decision"*) + one fact relevant to the expressed concern + safety-net or follow-up option. |
| 2 | Autonomy + options, but missing safety-net or concern-tailoring. |
| 1 | Educational lecture or data-dump without explicit autonomy support = pseudo-Secure.  A message over 60 words with no autonomy language is pseudo-Secure regardless of content quality. |

**Notes**
- A turn that opens with brief emotional acknowledgment (*"I know, that's hard…"*) and then
  provides autonomy support + tailored education is Secure (not Mirror).  Use Mirror or
  Mirror+Secure only when the reflective opening *substantially* addresses an expressed concern.
- Securing for a concern not yet Mirrored reduces the score by 1 (does not apply to
  Mirror+Secure).
- **Mirror vs Secure decision rule**: Secure REQUIRES at least one of: (a) a factual claim or
  educational content, (b) explicit autonomy affirmation, (c) a concrete option or safety-net.
  If a turn ONLY contains reflection, validation, normalization, or emotional attunement — with
  NO facts, education, autonomy language, or options — it is Mirror, not Secure.

---

## 3. Dependency Rules

1. The expected order is **Announce → Inquire → Mirror → Secure**.
2. **Mirror+Secure** and **Mirror+Secure+Inquire** are valid once rapport is established; they
   count against each component step in the session metrics.
3. Securing for a concern not yet Mirrored → score reduced by 1 (plain Secure only; not
   Mirror+Secure).
4. Mirroring something the person never expressed → not valid Mirror.
5. The AIMS flow is *cyclical*, not strictly linear.  Inquire and Mirror may recur after Secure
   if new concerns surface.

---

## 4. Deterministic Post-Processing Rules

After the LLM classifies, a series of deterministic guards are applied in this order.

### 4.1 Phase Guard (`_apply_phase_guard`)

**Rule 1 — Announce only happens once.**
If `step == "Announce"` and Announce has already been done (`prior_announced = True`):

| Message content | Reclassified as |
|-----------------|-----------------|
| Mirror stem + question mark | Mirror+Inquire |
| Mirror stem only | Mirror |
| Question mark only | Inquire |
| Neither | Secure |

**Rule 2 — PreAnnounce forward guard.**
If `prior_phase == "PreAnnounce"` **and** `prior_announced == False` and `step` is Secure, Mirror,
Mirror+Inquire, or Mirror+Secure, and vaccine content is detected in the message → reclassify as
Announce.

*This guard explicitly checks `prior_announced` so that it does not fire in the window between
Announce and the first Inquire (when phase is still "PreAnnounce" but announced is True).  This
prevents a correctly-classified Mirror+Inquire from being wrongly reclassified as a second
Announce.*

---

### 4.2 Soft Announce Detector (`_apply_overrides`)

Fires **before** all other overrides, when `prior_announced == False`.

Triggers when:
- LLM returned **null** step + message contains vaccine content (`_SOFT_ANNOUNCE_RE`)
- LLM returned **Inquire** + no Announce in steps + message contains vaccine content

Action: promotes to **Announce score 1** with a tip to use presumptive language.

Rationale: the LLM commonly misses soft vaccine introductions buried in long clinical
assessments (e.g. *"…and while I have you here, I like to check on vaccines during visits like
this — especially measles and whooping cough protection."*).

---

### 4.3 Positive Announce Detector (`_apply_overrides`)

If LLM did **not** classify as Announce and the message contains a strong presumptive phrase
(`_STRONG_ANNOUNCE_PHRASES`: *"i recommend"*, *"it's time for"*, *"due for"*, *"routine vaccines"*, etc.)
→ promotes to Announce.

---

### 4.4 Question Guard (`_apply_overrides`)

If message ends with `?` and step is Announce or Secure, but no `_ANNOUNCE_MARKERS` are present
→ ensures Inquire is present in steps and caps score at 2.

`_ANNOUNCE_MARKERS` includes: *"vaccination status"*, *"vaccine status"*, *"mmr vaccine"*,
*"measles protection"*, *"vaccinated"*, *"been vaccinated"*, all strong presumptive phrases.

---

### 4.5 Closing-Turn Guard (`_apply_overrides`)

Fires on Inquire steps **after** the Question Guard, when `prior_announced == True`.

Condition: at least **2 of 3** closing-turn signal categories are present:
- **Literature cues** (`_CLOSING_LITERATURE_CUES`): *"information"*, *"take home"*, *"read on your"*,
  *"look over"*, *"materials"*, *"handout"*, *"send you home with"*, etc.
- **Follow-up cues** (`_CLOSING_FOLLOWUP_CUES`): *"follow-up"*, *"book a"*, *"come back"*,
  *"next visit"*, *"schedule a"*, etc.
- **Autonomy cues** (`_SECURE_AUTONOMY_CUES`): same list as pseudo-Secure check.

Action: overrides Inquire → **Secure score 2**, clears tips.

Rationale: proposal-style questions like *"Why don't we book a follow-up?"* are not
concern-surfacing; a turn offering literature + follow-up + autonomy is categorically
Secure.  The guard must fire **after** the Question Guard because the Question Guard may
have already flipped a valid Secure → Inquire based solely on the trailing `?`.

---

### 4.6 Mirror Rebuttal Penalty (`_apply_overrides`)

Fires on Mirror / Mirror+Inquire steps **only** (exempt for Mirror+Secure).

Condition: `_has_rebuttal_but(msg)` — True when "but" appears in the **same sentence** as a
reflective stem (*"i hear you"*, *"it sounds like"*, *"that's fair"*, *"that makes sense"*, etc.).

Action: caps score at 1, adds reason *"Reflection included direct rebuttal → penalized"*.

"But" appearing in a separate educational sentence does **not** trigger the penalty.

---

### 4.7 Pseudo-Secure Penalty (`_apply_overrides`)

Fires on Secure steps (exempt for Mirror+Secure).

Condition: message > 60 words AND no `_SECURE_AUTONOMY_CUES` AND no `?` in message.

Action: caps score at 1, adds reason about data-dumping without autonomy support.

`_SECURE_AUTONOMY_CUES` includes: *"it's your decision"*, *"up to you"*, *"your choice"*, *"i'm here
to support"*, *"not rushed"*, *"you can decide"*, *"entirely up to you"*, etc.

---

## 5. Phase State Machine

Tracked concerns are canonical concern objects, not raw transcript snippets. `desc` is retained
as a short display summary for compatibility, while `id`, `canonical_label`, `summary`,
`evidence`, `status`, `mirror_count`, and `secure_count` carry the state model. New person
messages with the same canonical topic/meaning update the existing concern evidence instead of
appending a fresh unresolved concern.

| Phase | Meaning | Transition in |
|-------|---------|---------------|
| `PreAnnounce` | Vaccines not yet introduced | Initial state |
| `InquireMirror` | Active concern exploration | Any Inquire, Mirror, or Mirror+Inquire turn; Mirror+Secure when unmirrored concerns remain |
| `Secure` | Concerns addressed, relationship secured | Secure turn (all concerns mirrored); Mirror+Secure when all concerns mirrored |

**Special cases**
- After **Announce**, phase stays `PreAnnounce` until the first Inquire (this is intentional;
  the phase guard uses `prior_announced` separately from `prior_phase` to handle this window).
- **Mirror** always returns to `InquireMirror`, even from `Secure` — the flow is cyclical.
- **Mirror+Secure**: if all concerns are now mirrored after the turn, phase advances to `Secure`;
  otherwise stays in `InquireMirror`.
- **Inquire**, **Announce+Inquire**, **Mirror+Inquire**, **Secure+Inquire**, and
  **Mirror+Secure+Inquire** set `first_inquire_done = True` and phase to `InquireMirror`,
  even from `Secure`, unless global reconciliation advances fully resolved concern state to
  `Secure`.

---

## 6. Session Metrics

All step counts and scores are accumulated per session in `aims.perStepCounts` and
`aims.scores`.

**Expansion of compound steps:**
- `Announce+Inquire` score → counted in both Announce and Inquire score arrays
- `Mirror+Inquire` score → counted in both Mirror and Inquire score arrays
- `Mirror+Secure` score → counted in both Mirror and Secure score arrays
- `Secure+Inquire` score → counted in both Secure and Inquire score arrays
- `Mirror+Secure+Inquire` score → counted in Mirror, Secure, and Inquire score arrays

Running averages per step (`runningAverage`) are recalculated after each turn.

---

## 7. Vaccine Relevance Gate

Before phase guard runs, `VaccineRelevanceGate` checks whether the turn is vaccine-related.  If
not, the AIMS step is suppressed and replaced with a "waiting for vaccine Announce" placeholder.

Vaccine relevance is True if any of the following apply:
- Message text contains a cue from `VAX_CUES` (vaccin, shot, mmr, measles, immunity, …)
- Parent's last message contains a cue
- Prior concerns context contains a cue
- `prior_announced == True` (once vaccines are introduced, all turns are vaccine-relevant)

---

## 8. Endgame Detection

### 8.1 Hard guards (no LLM call)
- Phase is `PreAnnounce` → no endgame
- Not announced and ≤ 1 assistant turn → no endgame
- Any concerns tracked with `is_mirrored == False` → no endgame, except when the person's latest
  replies clearly accept literature/materials plus follow-up. That closure is allowed because
  residual uncertainty plus a follow-up plan is a valid AIMS outcome.

### 8.2 LLM detector (`endgame_detector.txt` prompt)
Called when hard guards pass.  Returns:
- `is_endgame` (boolean)
- `resolution_type`: `accepted_vaccine` | `accepted_literature` | `deferred` | `not_resolved`
- `summary`: one-sentence description of the outcome

The LLM is instructed to judge **intent, not exact wording**.  Natural language like *"two or
three weeks should give me enough time to look things over"* = `accepted_literature`.

### 8.3 Confirmation gates
- **`accepted_vaccine`**: requires heuristic confirmation via `EndGameDetector.detect()` (checks
  `ACCEPT_NOW_CUES` like *"let's do it"*, *"i consent"*, *"go ahead"*).  This gate is retained
  because consenting to vaccinate today is irreversible.
- **`accepted_literature`**: trusted from the LLM when hard guards pass. Natural language for
  literature plus follow-up is too varied for reliable keyword matching.
- **`deferred`**: never ends the scenario. If the LLM returns `deferred`, the runtime forces
  `is_endgame` to false so coaching can continue with a nudge or next-step suggestion.

### 8.4 Heuristic fallback
If LLM detection errors (`reason == "detection_error"`), `EndGameDetector.detect()` is used as
a fallback.  It requires both `FOLLOWUP_CUES` and `LITERATURE_CUES` to match, or `LITERATURE_CUES`
+ "appreciate"/"home" in the text.

---

## 9. Common Misclassifications (and how the system handles them)

| Pattern | Wrong | Correct | Handled by |
|---------|-------|---------|------------|
| Long clinical assessment + soft vaccine mention at end | rapport/null | Announce score 1 | Soft Announce detector + prompt example |
| First vaccine mention phrased as concern-invite ("what are your thoughts?") | Inquire | Announce score 1 | Soft Announce detector (Inquire → Announce pre-announcement) |
| Same message as Announce but with status question ending in "?" | Inquire | Announce | Question Guard (`_ANNOUNCE_MARKERS`) |
| Blended validation + education | penalized Mirror | Mirror+Secure score 2 | Mirror+Secure step + prompt guidance |
| "But" in a separate educational clause of a Mirror turn | Mirror score 1 | Mirror score 2 | Rebuttal penalty narrowed to same-sentence co-occurrence |
| Mirror+Inquire after Announce already done | Announce | Mirror+Inquire | Phase guard Rule 1 |
| Mirror/Secure before Announce when vaccine content present | Mirror/Secure | Announce | Phase guard Rule 2 |
| Long education without autonomy language | Secure score 2+ | Secure score 1 | Pseudo-Secure penalty |

---

## 10. Scoring Tip Policy

- At most **one tip** per turn (enforced by `classify_turn`).
- Tips are suppressed when all known concerns have already been mirrored (tip would be stale
  advice to mirror a concern that was already addressed).
- "Secure before mirror" tips escalate on repetition: first occurrence = standard nudge; second
  = names the unmirrored topic; third+ = pattern-level observation.
- Tips from reclassified steps (phase guard) are cleared so stale Announce tips don't leak into
  Mirror/Secure feedback.
