# Generify Deferred Issues

Remaining actionable tasks only.

## High priority

- Replace the remaining legacy `coach` request flag with a formal API migration
  to `moduleOptions.feedbackEnabled`, then remove `coach` from
  [app/models.py](/Users/craigburnett/PycharmProjects/AIMSBot/app/models.py)
  once clients are updated.

## Medium priority

- Generalize startup artifact presentation beyond the current
  "one primary artifact plus inline cards" shell model if a future module needs
  multiple first-class startup surfaces.
- Add a second fully featured module summary schema if another real module
  needs rich reporting, so cross-module summary semantics are exercised in
  production code rather than only through the "unsupported summary" path.

## Low priority

- Remove the `LegacyChatHandler` compatibility alias from
  [app/modules/aims/services/legacy_chat_handler.py](/Users/craigburnett/PycharmProjects/AIMSBot/app/modules/aims/services/legacy_chat_handler.py)
  once no internal or external code still imports it.
- Broaden legacy archive/module inference only if the app needs to read mixed
  historical module data in shared buckets or cross-deployment archive readers.
- Do another documentation cleanup pass if the repo stops being primarily AIMS
  and needs broader product-neutral guidance.
