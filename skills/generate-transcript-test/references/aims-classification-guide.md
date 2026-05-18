# AIMS Classification Guide for Transcript Analysis

Use this guide when determining the correct AIMS step and score for each clinician turn in a transcript.

## The AIMS Steps

### Announce
First (and only) introduction of vaccines. Fires once per session.
- Score 3: Presumptive recommendation + rationale + dialogue invite
- Score 2: Clear recommendation but missing rationale OR invite
- Score 1: Soft/indirect introduction, no presumptive phrasing
- Trailing status questions ("Can I ask about vaccination status?") stay as Announce, not Inquire

### Announce+Inquire
First vaccine introduction + open concern-surfacing question in same turn.
- Score 3: Presumptive recommendation + rationale + strong open question about concerns
- Score 2: Clear recommendation + open question, missing rationale or slightly leading
- Score 1: Soft introduction + closed/leading question
- Status questions do NOT count as Inquire — use plain Announce

### Inquire
Open question to surface concerns/hesitancy (must follow Announce).
- Score 3: Single, open, neutral, non-leading question
- Score 2: Decent but stacked or slightly leading
- Score 1: Closed, "why" directed at parent, or leading
- Questions about status/history = Announce, not Inquire

### Mirror
Reflect the person's concern so they "feel felt."
- Score 3: Accurate reflection + accuracy check ("Did I get that right?")
- Score 2: Decent reflection without accuracy check. Semantic mirroring (restating in clinician's own words) qualifies. Empathic normalization ("most parents feel the same way") qualifies when it validates a specific expressed concern.
- Score 1: Same-sentence "but" pivot that contradicts the reflection

**Critical rule — Mirror vs Secure**: If a turn ONLY contains reflection, validation, normalization, or emotional attunement — with NO facts, education, autonomy language, or options — it is Mirror, NOT Secure. Secure requires at least one of: (a) factual content, (b) autonomy affirmation, (c) concrete options/safety-net.

Examples of Mirror (NOT Secure):
- "You feel responsible for filtering all of that information. It makes sense that your guard would go up." → Mirror score 2 (pure reflection, no education)
- "You're trying to protect him from harm, not avoid caring for him." → Mirror score 2 (reframing hesitancy as protective intent)

### Mirror+Secure
Reflection of concern followed by autonomy-supportive education, same turn.
- Score 3: Clear mirror + accuracy check + autonomy + tailored fact
- Score 2: Decent mirror + reasonable autonomy + education
- Score 1: Mirror component vague/absent, or same-sentence rebuttal

Example:
- "Most parents aren't trying to be difficult — they're trying to be careful. [Mirror] The better question is, compared to the diseases, where does the balance of risk land? [Secure]" → Mirror+Secure score 2

### Mirror+Inquire
Reflection followed by open question about concerns.
- Score 3: Accurate reflection + accuracy check + strong open question
- Score 2: Decent reflection + decent open question
- Score 1: Weak mirror or closed/leading question

### Secure+Inquire
Securing one concern + open question for more concerns.
- Score 3: Autonomy + fact + safety-net + strong open question
- Score 2: Decent Secure + decent question
- Score 1: Weak component

### Secure
Affirm autonomy, offer ONE tailored fact, provide safety-net.
- Score 3: Explicit autonomy ("It's your decision") + relevant fact + safety-net/follow-up
- Score 2: Autonomy + options but missing safety-net or concern-tailoring
- Score 1: Educational lecture without autonomy support (pseudo-Secure)

Autonomy phrases to look for: "it's your decision", "up to you", "your choice", "don't have to", "without pressure", "no pressure", "not to corner", "take your time", "you can decide", "whatever you choose"

## person_topic Values

Assign based on what the PARENT is expressing (not the clinician):
- `trust` — distrust of sources, conflicting information, "who to believe"
- `autonomy` — feeling pressured, wanting to decide for themselves
- `side_effects` — worried about vaccine reactions
- `ingredients` — concerned about what's in vaccines (chemicals, preservatives)
- `immune_load` — too many vaccines, overwhelming immune system
- `schedule_timing` — wanting to delay or space out vaccines
- `effectiveness` — doubting whether vaccines work
- `autism` — concern about autism link
- `null` — parent is acknowledging, accepting, or not expressing a concern

Use `null` when the parent is wrapping up, agreeing to a plan, or just saying "that sounds good." Only assign a topic when the parent is actively expressing or reiterating a concern.

## Common Misclassification Patterns

1. **Pure reflection classified as Secure**: If there are NO facts, NO autonomy phrases, NO options — it's Mirror, not Secure
2. **Empathic normalization + education classified as rapport**: This is Mirror+Secure, not null/rapport
3. **Trailing question on education classified as just Secure**: If it ends with "How does that sit with you?" it may be Secure+Inquire
4. **Semantic mirror scored at 1**: Clinician-style reflections without formulaic stems should score 2, not 1

## Deterministic Override Awareness

The test pipeline has deterministic overrides that may modify what the LLM returns. Be aware of:
- **Pseudo-Secure penalty**: Caps Secure score at 1 if message >60 words AND no autonomy cues AND no "?"
- **Question Guard**: Flips Secure→Inquire if message ends with "?" and has no announce markers (post-Announce only)
- **Mirror rebuttal penalty**: Caps Mirror score at 1 if "but" co-occurs with a reflective stem in the same sentence

When setting expected scores, account for these overrides. If a Secure message has autonomy phrases like "don't have to" or "without pressure", it should NOT be penalized. If it lacks them and is >60 words, expect score 1.
