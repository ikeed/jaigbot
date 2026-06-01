---
name: generate-transcript-test
description: Generate an AIMS coaching integration test from an AIMSBot session transcript JSON file. Use this skill when the user provides a transcript JSON export (from AIMSBot) and wants to create a regression/integration test that replays the dialog through the coaching pipeline. Trigger when: user mentions "transcript test", "integration test from transcript", "test from convo", "generate test from JSON", or provides a session export JSON and asks for a test.
---

# Generate AIMS Transcript Integration Test

Given an AIMSBot session transcript JSON file, analyze the dialog, determine the correct AIMS classifications for each clinician turn, and generate a pytest integration test that replays the conversation through the full coaching pipeline.

## Step 1: Read and Parse the Transcript

Read the JSON file the user provides. The format is:

```json
{
  "history": [
    {"role": "assistant", "content": "parent message"},
    {"role": "coach", "content": "coaching note"},
    {"role": "user", "content": "clinician message"},
    ...
  ],
  "aims_state": { ... },
  "aims": { ... },
  "character": "...",
  "scene": "..."
}
```

Key roles:
- `"user"` = clinician (the person being coached)
- `"assistant"` = parent/patient (the simulated persona)
- `"coach"` = the coaching feedback for the PRECEDING clinician turn

Extract the interleaved turns in order. Each coaching cycle is:
1. Parent says something (assistant)
2. Coach gives feedback on previous clinician turn (coach)
3. Clinician says something (user)
4. Parent responds (assistant)

## Step 2: Identify Clinician Turns and Parent Replies

From the history, extract:
- **CLINICIAN_TURNS**: All `role=user` messages in order
- **PARENT_REPLIES**: The `role=assistant` message that FOLLOWS each clinician turn (this becomes the mocked patient reply for that turn)
- **INITIAL_PARENT_MSG**: The `role=assistant` message that appears BEFORE the first clinician turn (this seeds `person_last` for the first turn)

## Step 3: Classify Each Clinician Turn

For each clinician turn, determine the correct AIMS classification by reading `references/aims-classification-guide.md` (read it now). Apply these rules to each clinician message:

**Classification decision procedure:**
1. Does it introduce vaccines for the first time? → Announce (or Announce+Inquire if it also asks an open concern question)
2. Does it ask an open question about concerns/hesitancy? → Inquire
3. Does it ONLY contain reflection, validation, normalization, or emotional attunement — with NO facts, education, autonomy, or options? → Mirror
4. Does it contain both reflection AND educational content or autonomy support? → Mirror+Secure
5. Does it contain educational content, autonomy affirmation, options, or safety-netting? → Secure
6. Does it reflect a concern AND ask an open question? → Mirror+Inquire
7. Does it secure a concern AND ask for more? → Secure+Inquire

**Scoring:**
- Score 3 = full execution of the step (all expected elements present)
- Score 2 = decent but missing one element (e.g., mirror without accuracy check)
- Score 1 = notable flaw (e.g., same-sentence rebuttal, no autonomy in Secure)

**person_topic**: Determine what concern the parent is expressing. Use `null` when the parent is just acknowledging/accepting (not raising a new or ongoing concern). Valid values: `autism`, `immune_load`, `side_effects`, `ingredients`, `schedule_timing`, `effectiveness`, `trust`, or `null`.

## Step 4: Determine Initial State

From the transcript's `aims_state`, reconstruct the state that existed BEFORE the first visible clinician turn:
- `announced`: Was Announce already done?
- `phase`: Current AIMS phase
- `first_inquire_done`: Has any Inquire happened?
- `parent_concerns`: Which concerns exist and their mirrored/secured status
- `mirrors_done`: How many Mirror turns have occurred

If concerns in the export are marked `is_mirrored: false`, and a Mirror turn in the visible transcript should have addressed them, the initial state should have them as unmirrored so the test verifies the pipeline marks them correctly.

## Step 5: Generate the Test File

Generate a test file following the exact pattern in `tests/integration/test_transcript_georgina.py`. Read that file for the canonical structure.

Key elements:
1. **Module docstring** describing the transcript source
2. **CLINICIAN_TURNS** list with the exact clinician messages
3. **PARENT_REPLIES** list with the exact parent responses
4. **INITIAL_PARENT_MSG** — the parent message before the first visible clinician turn
5. **EXPECTED_CLASSIFICATIONS** — list of dicts, one per turn, each with `"classify"` (the full LLM response) and `"reply"` (the parent reply text)
6. **TranscriptStub** class — copy verbatim from the reference test
7. **Fixtures** — `MOCK_MAPPING`, `SESSION_ID`, `setup_env`, `_seed_session`, `_post_turn` — adapt `SESSION_ID` and `_seed_session` to match the transcript's state
8. **Test class** with three test methods:
   - `test_full_transcript_replay`: Per-turn assertions on step, score, no-rapport
   - `test_concern_mirroring_unblocks_endgame_guard`: All concerns mirrored after replay
   - `test_coach_notes_in_history_match_steps`: Coach notes match expected steps

**Naming**: Derive the test file name from the persona name in the transcript (e.g., `test_transcript_zia.py` for persona "Zia"). Use the persona name in the class name too (e.g., `TestZiaTranscript`).

**Output path**: `tests/integration/test_transcript_{persona_name_lower}.py`

## Step 6: Run and Verify

After generating the test, run it:
```bash
python3 -m pytest tests/integration/test_transcript_{name}.py -v --tb=short
```

If assertions fail, debug by examining:
- Did a deterministic override (pseudo-Secure penalty, Question Guard) change the score or step?
- Is the `_SECURE_AUTONOMY_CUES` list missing a phrase from the clinician's message?
- Did `person_topic` cause an unexpected concern registration?

Fix the test expectations or the codebase as appropriate, then re-run.
