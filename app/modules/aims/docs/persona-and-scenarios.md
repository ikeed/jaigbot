# AIMS personas and scenarios

This document covers the AIMS module's persona rotation and scenario-owned
participant context. Generic memory/session behavior remains in
[`docs/memory-and-persona.md`](/Users/craigburnett/PycharmProjects/AIMSBot/docs/memory-and-persona.md).

## Persona selection in Chainlit

For AIMS sessions, new personas are selected by user history. The app keeps
per-user persona interaction counts in Redis using non-expiring keys, backfills
the cache from GCS archives when needed, and chooses among personas with weight
`1 / (previous_interactions + 1)`. This makes personas a user has seen less
often more likely without making any persona impossible to select.

## AIMS participant context

The current AIMS shell still uses compatibility-shaped participant context:

- `character`
- `scene`
- `personaName`
- `initialCard`

The AIMS module owns how those are produced and interpreted during startup.

## Source materials

The following AIMS-owned source materials now live with the module docs:

- [Chat bot personas.docx](/Users/craigburnett/PycharmProjects/AIMSBot/app/modules/aims/docs/Chat%20bot%20personas.docx)
- [Scenarios.docx](/Users/craigburnett/PycharmProjects/AIMSBot/app/modules/aims/docs/Scenarios.docx)
- [AIMS protocol runtime map](/Users/craigburnett/PycharmProjects/AIMSBot/app/modules/aims/docs/README.md)
- [AIMS protocol summary](/Users/craigburnett/PycharmProjects/AIMSBot/app/modules/aims/docs/AIMS_Approach_Summary.md)
