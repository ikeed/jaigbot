# Multilingual-Readiness Cleanup Plan

## Purpose

This is a cleanup plan, not a multilingual implementation plan. The goal is to
reduce English-specific brittle logic now so the app is easier to localize later.

The current architecture already has the right broad shape: the LLM classifier is
the primary path, and deterministic code applies post-processing, state updates,
fallbacks, and rendering. The problem is that too many deterministic layers still
make semantic decisions by searching English prose, and several display layers
reshape generated text after the API returns it.

## Execution Boundary

The cleanup should not mean "move English regex classifiers into a localized
catalog." Localized catalogs are acceptable for display copy, prompt text,
browser UI strings, and explicitly quarantined legacy fixtures. They are not a
replacement for semantic classification.

Default runtime behavior should be:

- AIMS step, concern events, mirror/secure state, vaccine relevance, and
  endgame resolution come from LLM-returned structured fields.
- Deterministic code validates schemas, enum values, score ranges, state
  transitions, deduplication, persistence, and rendering.
- If the semantic classifier is unavailable, the app fails closed with neutral
  coaching-unavailable feedback or uses a model fallback. It does not silently
  guess with English regex classifiers.
- Regex/keyword classifiers may remain only behind an explicit legacy fallback
  switch for historical regression tests, diagnostics, and emergency fallback
  experiments.
- Model-authored feedback text is not rewritten at display time. Wording
  consistency, including "Mirror" rather than "Reflect," belongs in prompts,
  schemas, and regression tests.

## Guiding Principles

1. Text is not state.
   - A human sentence should not be parsed later to recover step, phase, tone,
     feedback type, concern topic, or outcome.
   - Store and pass canonical fields, then render localized text at the edge.

2. Let the model handle language semantics.
   - A model can decide whether a turn is Announce, Inquire, Mirror, Secure,
     active concern, acceptance, closure, or rapport.
   - Deterministic code should validate allowed values, preserve state, enforce
     lifecycle invariants, and choose safe fallbacks.

3. Keep deterministic rules when they are structural.
   - Good deterministic examples: enum validation, score range checks, allowed
     phase transitions, "Announce is only counted once", "do not mark an
     unmirrored concern secured unless the semantic event says it was secured".
   - Brittle deterministic examples: "does the text contain `what`, `why`,
     `but`, `handout`, `follow-up`, or `right?`".

4. Prefer reason codes plus localized display text.
   - Store `feedback_code`, `observation_code`, `topic`, `tone`, and
     `evidence_spans`.
   - Render English text from those fields for now. Later, swap the renderer or
     message catalog without changing classifier logic.

5. Fix behavior through contracts before deleting heuristics.
   - Add structured contracts and shadow comparison first.
   - Retire heuristic branches only after tests show the structured path covers
     the known regression corpus.

## Current Hotspot Inventory

Search summary for the main files inspected:

| File | Approximate hotspot count | Main issue |
| --- | ---: | --- |
| `app/aims_engine.py` | 51 | English regex and cue-list classifier/scorer fallback |
| `app/services/coach_post.py` | 30 | Vaccine relevance, endgame, and prose sanitizer heuristics |
| `app/services/conversation_service.py` | 26 | Concern topic, acceptance, duplicate, mirror/secure matching heuristics |
| `app/services/aims_state_service.py` | 15 | Topic cues, trust style cues, closure-plan cues, user-facing tip injection |
| `app/services/coaching_tip_sanitizer.py` | 11 | Regex-based contradiction cleanup for feedback |
| `app/services/aims_endgame_service.py` | 10 | Heuristic confirmation around endgame LLM result |
| `app/services/chat_helpers.py` | 8 | Prompt/history concern extraction and reply header stripping |
| `app/services/chainlit/orchestrator.py` | 7 | Structured coaching flattened into pipe-delimited display text |
| `app/services/summary_service.py` | 3 | Regex rewrite of LLM summary bullets |
| `app/services/chainlit/ui_handler.py` | 2 | Parses coach text separators/prefixes for display |
| `app/services/patient_reply_service.py` | 2 | English fallback/rewrite of terse patient replies |

The counts are intentionally rough. They include some harmless mechanical text
handling, but they identify where the cleanup effort should focus.

### Code Reference Map

These are the concrete code regions scanned for this plan. Line numbers are
current as of this document and should be rechecked before implementation.

| Area | Current code references |
| --- | --- |
| Canonical AIMS runtime map | `docs/aims/README.md:1-64` |
| Canonical current classification rules | `docs/aims/classification-scoring-rules.md:1-260` |
| Deterministic fallback classifier/scorer | `app/aims_engine.py:22-31`, `app/aims_engine.py:39-86`, `app/aims_engine.py:125-293`, `app/aims_engine.py:296-309`, `app/aims_engine.py:323-533` |
| LLM classifier parsing and fallback | `app/services/classifier_service.py:41-145`, `app/services/classifier_service.py:225-251` |
| Timeout fallback to deterministic evaluator | `app/services/aims_turn_coordinator.py:81-127` |
| Coaching flow mutation order | `app/services/aims_coaching_handler.py:320-366` |
| API response coaching assembly | `app/services/aims_coaching_handler.py:449-467` |
| Prompt concern-state prose | `app/services/aims_coaching_handler.py:83-118` |
| Patient reply header stripping | `app/services/aims_coaching_handler.py:491-505`, `app/services/chat_helpers.py:109-148` |
| Tip and step-feedback sanitizer | `app/services/coaching_tip_sanitizer.py:10-50`, `app/services/coaching_tip_sanitizer.py:53-95`, `app/services/coaching_tip_sanitizer.py:98-166` |
| Stateful coaching guidance and topic cues | `app/services/aims_state_service.py:33-157`, `app/services/aims_state_service.py:295-349`, `app/services/aims_state_service.py:351-419`, `app/services/aims_state_service.py:421-471`, `app/services/aims_state_service.py:473-563` |
| Concern topic, acceptance, mirror, and secure matching | `app/services/conversation_service.py:26-53`, `app/services/conversation_service.py:56-184`, `app/services/conversation_service.py:215-297`, `app/services/conversation_service.py:344-359`, `app/services/conversation_service.py:362-531`, `app/services/conversation_service.py:534-733` |
| Vaccine relevance and endgame cue logic | `app/services/coach_post.py:20-92`, `app/services/coach_post.py:142-298`, `app/services/aims_endgame_service.py:32-41`, `app/services/aims_endgame_service.py:93-177` |
| Post-processing and reason filtering | `app/services/coach_post.py:95-139`, `app/services/coach_feedback_history_service.py:46-110`, `app/services/coach_feedback_history_service.py:122-130` |
| Coach-post and summary prose cleanup | `app/services/coach_post.py:302-355`, `app/services/aims_endgame_service.py:207-242`, `app/services/summary_service.py:169-177`, `app/services/summary_service.py:209-236` |
| Patient reply fallback and rewrite | `app/services/patient_reply_service.py:43-59`, `app/services/patient_reply_service.py:69-97`, `app/services/patient_reply_service.py:112-132` |
| History concern extraction | `app/services/chat_helpers.py:53-106` |
| Chainlit coaching flattening | `app/services/chainlit/orchestrator.py:436-475`, `app/services/chainlit/orchestrator.py:486-500` |
| Chainlit coach formatting and scenario parsing | `app/services/chainlit/ui_handler.py:19-37`, `app/services/chainlit/ui_handler.py:40-60`, `app/services/chainlit/ui_handler.py:92-95` |
| Frontend persona/role scraping | `public/js/aimsbot/message-roles.js:25-39`, `public/js/aimsbot/message-roles.js:58-64`, `public/js/aimsbot/message-roles.js:76-123` |
| Prompt contracts already asking for JSON | `app/prompts/classify_turn.txt:1-35`, `app/prompts/aims_system_instruction.txt:180-202`, `app/prompts/aims_patient_reply.txt:12-18`, `app/prompts/aims_fallback_feedback.txt:17-25` |
| Existing JSON schema gap | `app/json_schemas.py:17-39` |
| Mechanical JSON extraction to keep centralized | `app/services/vertex_helpers.py:27-78` |

## Specific Problems Found

### 1. Deterministic AIMS fallback is a second English classifier

`app/aims_engine.py` implements a full fallback classifier and scorer using
English stem lists, regexes, punctuation, and cue matching. Examples:

- Small-talk and clinical token regexes near the top of the file.
- Announce fallback markers such as "i recommend", "routine vaccines", and
  "vaccination status".
- Inquire detection based on question marks and English question starters.
- Mirror detection based on English mirror-language stems.
- Secure detection based on English autonomy, option, and safety-net phrases.
- Scoring tips chosen by English checks such as `why`, `right?`, `but`, `how
  does that sound`, and `call if`.

Runtime impact:

- `ClassifierService` falls back to `evaluate_turn()` when classification fails.
- `AimsTurnCoordinator` also calls `evaluate_turn()` on timeout.
- Fallback feedback may then be refined by the LLM, but the step and score stay
  deterministic.

Cleanup direction:

- Stop treating `app/aims_engine.py` as a production semantic authority.
- Keep it temporarily as an emergency English-only fallback and regression
  reference.
- Introduce a model-backed semantic contract that returns canonical observations
  directly, then move fallback behavior toward "classification unavailable" or
  "retry with cheaper/faster model" instead of heuristic classification.

### 2. Concern tracking mixes semantic state with English cue matching

`app/services/conversation_service.py` and `AimsStateService.TOPICAL_CUES` track
concerns by substring matching and token overlap.

Examples:

- `topics_in()` and `concern_topic()` choose topics by English cue substrings.
- `_clean_evidence_snippet()` strips English rapport preambles.
- `_is_acceptance_message()` relies on English acceptance starts, hedges, and
  question starters.
- `maybe_add_person_concern()` mixes LLM `person_topic` with keyword-derived
  topics.
- `mark_mirrored_multi()` and `mark_secured_by_topic()` use keyword matching,
  token overlap, and fallback-to-first-unmirrored logic.

Runtime impact:

- The model already returns `person_topic`, but deterministic keyword fallback
  can still add, merge, mirror, or secure concerns based on English wording.
- User-facing concern labels are built in English inside state utilities.

Cleanup direction:

- Introduce a `ConcernEvent` contract from the classifier layer:
  - `event_type`: `raised`, `renewed`, `accepted`, `mirrored`, `secured`,
    `no_active_concern`
  - `topic`: canonical topic enum
  - `target_concern_id`: optional existing concern id
  - `evidence_spans`: short snippets from the triggering turn
  - `confidence`: bounded float or enum
- Let deterministic state code apply these events without inspecting natural
  language.
- Keep keyword matching only as a low-confidence diagnostic or shadow signal
  during migration.

### 3. Tip sanitization edits prose after classification

`app/services/coaching_tip_sanitizer.py` tries to remove or replace feedback that
criticizes a behavior already present in the current turn. The recorded prior
regression here is exactly the smell: an English regex matched "what's on their
mind" inside a valid pause tip and removed the wrong advice.

Runtime impact:

- The app asks the LLM not to suggest already-performed behavior.
- The sanitizer then reparses user-facing text and tries to infer whether the
  feedback is an "open question tip".
- Nested `step_feedback` and top-level `tips` can disagree unless both are
  sanitized in exactly the same way.

Cleanup direction:

- Replace prose sanitization with structured observations and feedback codes.
- Have the classifier return fields such as:
  - `observations.open_concern_question_present`
  - `observations.question_count`
  - `observations.leading_question_present`
  - `observations.why_framing_present`
  - `feedback_items[].target_observation`
- Validator rule: if a feedback item says `ask_open_question` while
  `open_concern_question_present=true`, reject or regenerate that item.
- Until that exists, keep sanitizer changes small and regression-tested.

### 4. Post-processors modify feedback by searching user-facing reasons

`AimsPostProcessor.post_process()` removes reasons containing words like
"judgment" or "leading" when autonomy-respecting language is present.
`CoachFeedbackHistoryService.filter_user_facing_reasons()` hides internal reasons
by prefix strings and suppresses "no clear recommendation" for non-Announce
steps.

Runtime impact:

- Internal control flow depends on English text generated for humans.
- New wording from the model can bypass filters or get filtered incorrectly.

Cleanup direction:

- Add `reason_type` or `visibility` to feedback items:
  - `internal_guard`
  - `model_feedback`
  - `state_guidance`
  - `user_visible`
- Add `feedback_code` for known cases:
  - `secure_before_inquire`
  - `secure_before_mirror`
  - `announce_after_inquiry`
  - `fallback_classifier`
  - `vaccine_not_introduced`
- Filter by code or visibility, never by English prefix.

### 5. Endgame detection uses LLM plus English confirmation heuristics

`AimsEndgameService` uses an LLM detector, then confirms or falls back with
`EndGameDetector.detect()`. The detector is a dense set of English acceptance,
follow-up, literature, negation, and active-concern cue lists.

Runtime impact:

- The LLM can identify endgame, but English heuristics can still accept, reject,
  or force outcomes.
- `accepted_literature` is particularly coupled to words like "handout",
  "follow-up", "read over", and "appointment".

Cleanup direction:

- Split endgame into structural prerequisites and semantic intent:
  - Structural: announced, concerns mirrored/secured as required, at least one
    relevant exchange, game not already ended.
  - Semantic: model-returned `resolution_type`, `accepted_action`,
    `remaining_active_concern`, `requested_followup`, `accepted_materials`.
- Keep deterministic rejection when structure is impossible.
- Remove deterministic acceptance based only on English text once the semantic
  contract is covered by tests.

### 6. API reply text is modified before display/history

Examples:

- `AimsCoachingHandler._strip_initial_reply_headers()` mutates
  `reply_payload["patient_reply"]`.
- `strip_appointment_headers()` removes lines starting with "Person:",
  "Parent:", "Patient:", "Purpose:", and "Notes:".
- `PatientReplyService.generate()` rewrites `"ok"` to hard-coded English
  fallback replies.
- The patient-reply prompt also forbids English labels because the app knows
  they leak into display.

Runtime impact:

- The API contract says `patient_reply` is display text, but the backend still
  has to clean it.
- If future outputs are localized, label stripping and fallback rewrites will be
  incomplete or wrong.

Cleanup direction:

- Treat metadata leakage as invalid model output, not display text to repair.
- On invalid reply:
  - retry once with a corrective prompt, or
  - return a typed fallback reply selected from a message catalog.
- Add an optional validation result:
  - `reply_valid`
  - `metadata_leak_detected`
  - `fallback_reply_code`
- Do not mutate valid `patient_reply` after schema validation except for purely
  mechanical trimming.

### 7. Chainlit display flattens structured coaching into prose

The API already returns a structured `coaching` object. But
`app/services/chainlit/orchestrator.py` immediately turns it into pipe-delimited
English text:

- step group headers such as `Secure:`
- `Feedback: ...`
- `Tip: ...`
- `Nudge: ...`
- joined with `" | "`

Then `UIHandler.format_coach_message()` reparses that string by splitting on
`" | "`, stripping "Conversation phase:", and detecting "Scenario complete".
`CoachFeedbackHistoryService` separately builds similar flattened strings for
history, while also preserving `coaching_data` in `full_history`.

Runtime impact:

- Display labels are hard-coded in English.
- Message history contains display prose as the primary coach content.
- Later rendering must parse separators and prefixes instead of structured data.

Cleanup direction:

- Keep `coaching_data` as the source of truth for live rendering and replay.
- Add a render method that accepts structured coaching, not a preformatted
  string.
- Store `coach_entry.content` as a compatibility summary only.
- Render labels from a small UI message catalog:
  - `coach.title`
  - `coach.step_group_header`
  - `coach.feedback`
  - `coach.tip`
  - `coach.nudge.deferred`
  - `coach.scenario_complete`
- Do not split on `" | "` after new structured rendering exists.

### 8. Summary and coach-post cleanup edits LLM prose

`sanitize_endgame_bullets()` removes code fences, JSON-looking lines, and
`patient_reply` artifacts. `_enforce_metrics_consistency()` rewrites summary
bullets if the model says an observed step was skipped. `_select_summary_commentary()`
filters bullets with structural prefixes and AIMS-score regexes.

Runtime impact:

- Some cleanup is mechanical and acceptable, such as removing code fences from a
  malformed model response.
- The risky part is changing or filtering meaning by matching English summary
  text.

Cleanup direction:

- Ask summary generation for structured sections:
  - `overall_commentary`
  - `strengths[]`
  - `growth_areas[]`
  - `metric_notes[]`
  - `coach_post_lines[]`
- Validate against session metrics before rendering.
- If validation fails, regenerate or drop the invalid section instead of
  rewriting English prose.

### 9. Frontend role decoration scrapes text and author labels

`public/js/aimsbot/message-roles.js` extracts persona names from scenario text
using labels like "Person:", "Parent:", and "Patient:", and maps author labels
such as "Doctor", "Coach", and "System" to display roles.

Runtime impact:

- This is not a classifier issue, but it is another case where structured data is
  available elsewhere yet the UI scrapes visible text.

Cleanup direction:

- Continue using author labels for Chainlit compatibility where required.
- Prefer window-message state for persona name and scenario metadata.
- Treat scenario card text as display-only, not as a metadata source.

## Proposed Target Contracts

### Classifier Result

Extend the existing `ClassifierResult` and `Coaching` shapes rather than adding a
parallel ad-hoc object.

Candidate fields:

```json
{
  "is_small_talk": false,
  "is_vaccine_relevant": true,
  "person_topic": "trust",
  "person_events": [
    {
      "event_type": "raised",
      "topic": "trust",
      "target_concern_id": null,
      "evidence_spans": ["I do my own research because the information conflicts"],
      "confidence": "high"
    }
  ],
  "aims": {
    "steps": ["Mirror", "Secure"],
    "score": 2,
    "observations": {
      "open_concern_question_present": false,
      "leading_question_present": false,
      "why_framing_present": false,
      "question_count": 0,
      "reflection_present": true,
      "accuracy_check_present": false,
      "autonomy_support_present": true,
      "safety_net_present": false,
      "followup_or_materials_present": true
    },
    "feedback_items": [
      {
        "step": "Mirror",
        "tone": "praise",
        "code": "specific_mirror_present",
        "text": "You mirrored the trust concern clearly.",
        "evidence_spans": ["You want to feel confident in the evidence"]
      },
      {
        "step": "Secure",
        "tone": "improvement",
        "code": "add_safety_net",
        "text": "Add what to watch for and how to reach you afterward.",
        "evidence_spans": []
      }
    ],
    "phase": "Secure"
  },
  "resolution": {
    "is_endgame": false,
    "resolution_type": "not_resolved",
    "accepted_materials": false,
    "accepted_followup": false,
    "accepted_vaccine": false,
    "remaining_active_concern": true
  }
}
```

The app does not need every field on day one. The important shift is that
downstream code validates codes and booleans, not English prose.

### Display Message Contract

Create a small renderer-facing shape:

```json
{
  "title_key": "coach.title",
  "items": [
    {
      "label_key": "coach.step_group_header",
      "value": "Mirror+Secure"
    },
    {
      "label_key": "coach.tip",
      "message": "Add what to watch for and how to reach you afterward."
    }
  ]
}
```

For now, `message` can remain English model text. Later it can become
`message_key` plus arguments for deterministic messages, or localized text from
the model when that is explicitly supported.

## Migration Plan

### Phase 0 - Freeze behavior and classify rules

No behavior changes yet.

Tasks:

- Build a current hotspot inventory test fixture from existing regression cases:
  - soft announce classification
  - borderline classification
  - announce/inquire regressions
  - coaching tip sanitizer regressions
  - endgame detection unit cases
  - Chainlit coach rendering/replay cases
- Tag each deterministic rule as one of:
  - `structural_keep`
  - `semantic_replace`
  - `mechanical_keep`
  - `compatibility_retire_later`
- Add comments or docs linking each `semantic_replace` rule to its future
  structured field.

Exit criteria:

- There is a single list of rules to preserve, replace, or retire.
- Tests document the current English behavior before any cleanup begins.

### Phase 1 - Harden schemas without changing output

Tasks:

- Expand Pydantic models for optional structured fields:
  - observations
  - feedback items with codes
  - concern events
  - resolution signals
- Keep old `reasons`, `tips`, and `step_feedback` fields for compatibility.
- Teach `ClassifierService` to parse and validate the new fields when present.
- Add telemetry that records whether the model returned complete structured
  fields.

Exit criteria:

- Existing clients still receive the same response shape.
- Tests prove new optional fields round-trip without changing current behavior.

### Phase 2 - Move concern tracking to semantic events

Tasks:

- Change `maybe_add_person_concern()` to prefer model-supplied `ConcernEvent`
  objects.
- Use keyword `topics_in()` only when semantic events are absent.
- Add confidence handling:
  - high confidence: apply event
  - medium confidence: apply only when unambiguous
  - low confidence: record diagnostic, do not mutate concern state
- Store concern IDs and event history so mirror/secure transitions target an
  existing concern instead of re-detecting topics from text.

Exit criteria:

- Existing concern-state tests pass.
- New tests show concern state can be updated from events without the original
  English text containing topic keywords.

### Phase 3 - Replace sanitizer logic with structured validation

Tasks:

- Add contradiction validation over `observations` and `feedback_items`.
- Convert known sanitizer cases into feedback-code validation:
  - open question already present
  - stacked questions
  - leading question
  - why-framing
  - pause-after-question needed
- If the model returns contradictory feedback, regenerate feedback only, or drop
  the invalid item and fall back to a coded deterministic message.
- Keep the current regex sanitizer behind a compatibility function until tests
  show it is no longer used.

Exit criteria:

- The prior pause-tip/open-question sanitizer regression is impossible because
  the app no longer identifies tip type by regexing the rendered sentence.
- Top-level tips and nested step feedback are validated by the same mechanism.

### Phase 4 - Render structured coaching instead of pipe-delimited prose

Tasks:

- Add `UIHandler.render_coaching(coaching: dict)` or equivalent.
- Change `ChainlitOrchestrator._process_backend_response()` to pass the
  structured `coaching` object to the renderer.
- Change `CoachFeedbackHistoryService` so `full_history[].coaching_data` is the
  replay source of truth.
- Keep `content` as a backward-compatible English summary during migration.
- Add a tiny English message catalog for labels, not full multilingual support:
  - step group header
  - feedback
  - tip
  - nudge
  - scenario complete

Exit criteria:

- No live rendering code has to split on `" | "`.
- No live rendering code has to parse display prefixes such as "Feedback:" or "Tip:".
- Replay still works for legacy history entries.

### Phase 5 - Replace endgame cue lists with semantic resolution fields

Tasks:

- Extend endgame detection output with:
  - `accepted_vaccine`
  - `accepted_materials`
  - `accepted_followup`
  - `deferred`
  - `remaining_active_concern`
  - `evidence_spans`
- Keep deterministic state prerequisites in `AimsEndgameService`.
- Retire `EndGameDetector.detect()` as an acceptance authority once semantic
  endgame tests cover the existing examples.
- Preserve `EndGameDetector` temporarily as a shadow diagnostic.

Exit criteria:

- Endgame decisions are accepted or rejected by structured fields plus state
  prerequisites.
- English acceptance phrases no longer drive production endgame decisions.

### Phase 6 - Make fallback behavior safe without heuristic classification

Tasks:

- Change timeout/error fallback strategy from "English heuristic classifier" to:
  1. retry with a lower-latency model when available;
  2. return neutral coaching unavailable state if classification still fails;
  3. continue patient reply if safe and valid.
- Keep `app/aims_engine.py` for tests or local diagnostic mode until confidence
  is high.
- Remove or feature-flag production use of `evaluate_turn()`.

Exit criteria:

- A model outage does not produce confidently wrong AIMS classification.
- Users see a graceful coaching-unavailable note rather than English-only
  heuristic feedback pretending to be semantic.

### Phase 7 - Clean patient reply and summary contracts

Tasks:

- Treat leaked metadata labels in `patient_reply` as validation failure.
- Retry invalid replies with a corrective prompt.
- Replace `"ok"` rewrite with a `fallback_reply_code` and catalog-rendered text.
- Change summary generation to structured sections instead of bullets requiring
  English regex cleanup.

Exit criteria:

- The app does not mutate model reply text before storing/displaying it, except
  trimming whitespace.
- Summary cleanup validates sections and metrics rather than rewriting prose.

## What To Keep Deterministic

Keep deterministic code for:

- JSON schema validation.
- Pydantic normalization.
- Enum mapping and backward-compatible alias handling.
- Phase-state transitions after semantic events are known.
- Score bounds.
- Deduplication by stable concern IDs.
- Session persistence and replay ordering.
- Security hard blocks for obvious prompt injection attempts, if they remain
  conservative.
- Mechanical JSON fence extraction and whitespace trimming.

Do not keep deterministic code as the final authority for:

- AIMS step classification.
- Open versus closed question classification.
- Concern topic detection from user prose.
- Mirroring/securing target detection from substring overlap.
- Acceptance, deferral, and endgame intent.
- Whether a feedback sentence is valid by regexing the sentence.
- UI state recovered from rendered English labels.

## Verification Strategy

Focused existing suites to keep close during this work:

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/unit/services/test_coaching_tip_sanitizer.py \
  tests/regression/test_announce_inquire.py \
  tests/unit/prompts/test_prompt_and_override_improvements.py \
  tests/unit/services/chainlit/test_chainlit_orchestrator.py
```

Additional relevant suites:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_aims_engine.py \
  tests/unit/test_aims_engine_branch_coverage.py \
  tests/unit/services/test_conversation_service.py \
  tests/unit/services/test_endgame_detection_unit.py \
  tests/unit/services/test_patient_reply_service.py \
  tests/unit/services/test_coach_feedback_history_service.py \
  tests/unit/services/test_coach_post_sanitizer.py \
  tests/regression/test_soft_announce_classification.py \
  tests/regression/test_borderline_classification_regressions.py \
  tests/regression/test_aims_replay_regressions.py
```

Before broad merges:

```bash
git diff --check
.venv/bin/python -m compileall -q app chainlit_app.py scripts tests
.venv/bin/python -m pytest --ignore=tests/integration -q
```

New tests to add during implementation:

- Contract tests for classifier structured fields.
- Golden transcript tests that compare old heuristic output to model structured
  output in shadow mode.
- Tests proving concern updates work when topic keywords are absent.
- Tests proving feedback contradiction checks use codes and observations, not
  prose.
- Chainlit live-render tests that assert structured coaching renders correctly
  without pipe-delimited content.
- Replay tests for both legacy flattened history and new structured history.
- Patient reply validation tests for metadata leakage and fallback reply codes.

## Recommended First Implementation Slice

Start with the smallest cleanup that reduces future pain without touching model
behavior:

1. Add structured renderer support for coaching while preserving old content.
2. Store/render from `coaching_data` where available.
3. Add message-label constants or a tiny English catalog for coach labels.
4. Keep the current pipe-delimited content only for legacy replay.

Why this first:

- The API already returns structured coaching.
- It avoids model behavior changes.
- It reduces the display/prose coupling immediately.
- It creates a pattern for later localization without committing to multiple
  languages now.

Second slice:

1. Add optional `observations` and `feedback_items[].code` to classifier parsing.
2. Keep current tips and step feedback.
3. Add validation that detects contradictions when those fields are present.
4. Run in shadow mode before replacing the sanitizer.

Third slice:

1. Add `ConcernEvent` support.
2. Prefer events over keyword topic detection.
3. Keep keyword detection as fallback/shadow telemetry.

This order gives the project cleaner contracts first, then gradually moves
semantic decisions out of regex code without destabilizing the coaching flow.
