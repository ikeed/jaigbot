# Log Bundle And Contextual Logging Plan

## Goal

When a user reports a bad session, the system should automatically preserve:

1. the archived conversation/session payload
2. a bounded, queryable log bundle for that same conversation

At the same time, app-owned logging should become more consistent so that log
collection is reliable, not heuristic-heavy.

This plan covers two related changes:

1. contextual logging standardization
2. automated bug-report log bundle collection

The desired end state is:

- a reported session in GCS has a neighboring log artifact
- app-owned logs consistently include enough correlation metadata to retrieve
  the right events
- the reporting flow remains fast and does not fail just because log export
  fails

## Scope

In scope:

- standardizing app-owned structured logging fields
- propagating request/session/module context automatically
- collecting report-time logs for a single session in a bounded window
- writing the collected logs into the same bug-report bucket/prefix family
- preserving staging/prod separation
- making fallback reasons and degraded reply behavior diagnosable

Out of scope for the first version:

- full normalization of third-party logs (`httpx`, `google_genai`, FastAPI,
  Cloud Run internals)
- replay tooling or automated diagnosis summaries
- cross-project or cross-service aggregation
- building a general-purpose observability platform
- requiring Cloud Run instance id as a primary correlation key

## Problem Statement

Today, debugging a broken conversation often requires manual correlation across:

- archived session JSON in GCS
- Cloud Run request logs
- AIMS telemetry events
- ad hoc filters using `requestId`, `sessionId`, timestamps, and model events

This has a few concrete problems:

1. not all app-owned logs consistently include `sessionId`
2. some logs are emitted through shared helpers, others are hand-rolled
3. bug reports store the conversation artifact, but not the corresponding log
   slice
4. some degraded paths are observable only indirectly
5. Cloud Logging queries are repetitive and easy to get wrong under pressure

The result is that production or staging RCA is slower than it should be.

## Design Principles

1. Correlate by business identifier first
   - `sessionId` is the primary conversation key
   - environment and service scope must also be included
   - Cloud Run instance id is optional supplemental metadata, not a required
     input

2. Keep report submission fast
   - the report endpoint should succeed even if log collection fails
   - log bundling should be async/background

3. Prefer structured app-owned logs
   - structured JSON should be the primary query surface
   - substring/text search is fallback only

4. Bound the log query aggressively
   - always constrain by service/environment and time window

5. Make degraded behaviors explicit
   - invalid JSON retry, reply timeout, rate limiting, normalization, and
     fallback use should all be visible as distinct events

6. Do not overfit to one deployment topology
   - the plan should work for staging and prod without relying on instance
     affinity

## Current State

As of now, the codebase already has useful pieces:

- structured telemetry helper:
  - `app/telemetry/events.py`
- request logging middleware and exception logging:
  - `app/http_handlers.py`
- AIMS turn lifecycle telemetry:
  - `app/modules/aims/services/aims_turn_telemetry.py`
- archived session/report flow:
  - `app/services/chat_orchestrator.py`
  - report storage logic and GCS session archives

Recent improvements already in place or in progress:

- reply fallback reasons are becoming more explicit
- request logs can include `sessionId` when present
- reply-path degradation is more observable than before

That means the platform is ready for a more systematic pass, not a greenfield
observability build.

## Target Architecture

### 1. Standard logging envelope

All app-owned structured logs should aim to carry the same top-level fields
when available:

- `event`
- `sessionId`
- `requestId`
- `moduleId`
- `appEnv`
- `serviceName`
- `userInfo` or `userId` when appropriate and safe
- request-specific fields:
  - `path`
  - `method`
  - `status`
  - `latencyMs`
- conversation-specific fields:
  - `step`
  - `phase`
  - `reason`
  - `modelId`
  - `modelUsed`

Required does not mean every log must have every field. It means the envelope
should be consistent enough that missing values are exceptional, not normal.

### 2. Context propagation

Request-scoped context should be propagated automatically so deep service code
does not need to manually thread metadata everywhere.

Preferred propagation model:

- middleware captures:
  - `requestId`
  - `sessionId`
  - `moduleId`
  - `appEnv`
  - possibly `userId`
- these values are stored in `contextvars`
- telemetry helpers and/or logging filters read those values by default
- explicit call-time fields still override inferred context

This is the cleanest path to consistent logging across layers.

### 3. Bug report bundle flow

When `/api/report` is called:

1. archive the session JSON to GCS
2. enqueue an asynchronous log-bundle collection task
3. query Cloud Logging for matching events
4. write the resulting log bundle next to the archived session

The report endpoint should return success once the report is accepted and the
bundle job is scheduled. It should not wait for the log query and export to
finish.

### 4. Log collector query strategy

Primary filters:

- `resource.type="cloud_run_revision"`
- `resource.labels.service_name="<service>"`
- environment marker where available
- `sessionId="<sid>"`
- bounded time window

Secondary strategy:

- if some app-owned log families still miss `sessionId`, use:
  - `requestId` discovered from matching conversation logs
  - bounded service/time window
  - text fallback if needed

The collector should prefer structured `sessionId` matching first.

## Data Model For Stored Bug Report Artifacts

Recommended storage layout:

- conversation/session archive:
  - `sessions/v1/user_id=<...>/session_id=<...>.json`
- collected logs:
  - `sessions/v1/user_id=<...>/session_id=<...>.logs.json`
- optional collector metadata:
  - `sessions/v1/user_id=<...>/session_id=<...>.logs.meta.json`

The metadata file is optional but useful. It could include:

- collector version
- report timestamp
- query window
- matched event count
- service/environment used
- whether fallback text search was needed
- whether the collection was partial or complete

## Recommended Log Bundle Format

The `.logs.json` artifact should not just be a raw dump with no framing.

Recommended structure:

```json
{
  "sessionId": "042ebccd-8300-4f35-bb79-f69846691bcf",
  "serviceName": "aimsbot-staging",
  "appEnv": "staging",
  "window": {
    "start": "2026-06-12T01:50:00Z",
    "end": "2026-06-12T02:06:00Z"
  },
  "events": [
    {
      "timestamp": "...",
      "severity": "INFO",
      "event": "request_start",
      "requestId": "...",
      "sessionId": "...",
        "payload": {
          "example": "..."
        }
    }
  ]
}
```

Why:

- it gives the artifact clear provenance
- it remains easy to inspect manually
- it is still machine-processable for future tooling

## Should This Be A Cloud Function?

### Recommendation for v1

Do **not** start with a separate Cloud Function.

Start with an async collector inside the same codebase, because:

- fewer moving parts
- same versioning as the report flow
- easier to iterate quickly
- no extra deploy/IAM surface initially

### When to split it out later

Consider moving to a dedicated Cloud Run service or job if:

- log collection becomes slow or flaky enough to affect app worker load
- you want separate IAM boundaries for log-reading and GCS writing
- you want retries, dead-letter handling, or independent scaling
- bug-report collection becomes a shared platform concern across services

If split out later, prefer a small Cloud Run service or job over an old-style
Cloud Function unless your platform standards strongly prefer Functions.

## Detailed Implementation Plan

## Phase 1: Standardize App-Owned Logging Context

### Objective

Make app-owned logs consistently carry correlation metadata.

### Tasks

1. Define the canonical logging fields
   - document required and optional top-level fields
   - decide exact naming:
     - `sessionId`
     - `requestId`
     - `moduleId`
     - `appEnv`
     - `serviceName`

2. Audit current log emission sites
   - request middleware and exception handlers
   - `telemetry/events.py`
   - AIMS telemetry classes
   - orchestrators
   - session/report paths
   - summary routes

3. Eliminate hand-rolled drift where practical
   - replace direct `logger.info(json.dumps(...))` with shared helper calls
     where that improves consistency
   - keep local direct logging only where justified

4. Add missing `sessionId` propagation
   - body
   - query params
   - request state
   - context propagation

5. Add missing `moduleId`, `appEnv`, `serviceName` where reasonable
   - not every log line needs all fields immediately
   - prioritize logs likely to land in report bundles

### Risks

- over-editing too many logging sites at once can create noisy diffs
- some logging is in hot paths; avoid expensive metadata assembly

### Mitigation

- start with request logging + telemetry helper + AIMS conversation events
- preserve behavior and payload semantics while enriching metadata

## Phase 2: Add Request-Scoped Context Propagation

### Objective

Reduce manual metadata threading by using context propagation.

### Tasks

1. Introduce a context module
   - likely using `contextvars`
   - getters/setters for:
     - request id
     - session id
     - module id
     - app env
     - maybe user id

2. Populate context in request middleware
   - on request start
   - ensure cleanup/reset is correct

3. Update telemetry helper to default from context
   - explicit arguments override context values

4. Optionally add a logging filter/formatter
   - enrich plain logs with the same context when possible

### Risks

- leaking context between requests if reset logic is wrong
- subtle async/task inheritance bugs

### Mitigation

- unit tests around context set/reset
- keep the helper override behavior explicit
- avoid using mutable shared global state

## Phase 3: Make Degraded Reply Behavior Fully Observable

### Objective

Ensure patient-reply degradation paths are explicit and queryable.

### Tasks

1. Emit structured events for:
   - invalid JSON attempt 1
   - invalid JSON attempt 2
   - timeout fallback
   - rate-limited fallback
   - exhausted-without-valid-reply fallback
   - terse `ok` normalization

2. Include correlation fields:
   - `sessionId`
   - `requestId` when available
   - `moduleId`
   - `reason`
   - `attempt`
   - whether there were open concerns

3. Ensure the reply path records the actual model used
   - especially after retry/fallback

### Risks

- duplicate logging across retry and coordinator layers

### Mitigation

- define clear ownership:
   - payload repair logging in `PatientReplyService`
   - timeout/rate-limit logging in coordinator

## Phase 4: Build The Log Collector

### Objective

Given a reported session, collect the relevant Cloud Logging slice and persist
it next to the archived session.

### Inputs

- `session_id`
- `service_name`
- `app_env`
- `reported_at`
- optional:
  - `window_before_s`
  - `window_after_s`
  - `request_ids`

### Tasks

1. Define collector API/contract
   - internal function or background task interface

2. Query Cloud Logging
   - structured filter first
   - service/environment bounded
   - timestamp bounded

3. Normalize matched records into export format
   - capture:
     - timestamp
     - severity
     - logName
     - text/json payload
     - requestId
     - sessionId

4. Write bundle to GCS
   - alongside session archive

5. Write metadata artifact if useful
   - counts, query window, fallback strategy used

### Risks

- Cloud Logging query latency
- incomplete coverage if some events still lack `sessionId`
- cost/verbosity if window is too large

### Mitigation

- keep windows narrow by default
- prefer sessionId matching first
- optionally widen only when needed

## Phase 5: Integrate With Report Flow

### Objective

Trigger log collection from the bug-report path without slowing it down.

### Tasks

1. Update `/api/report` orchestration
   - archive session as today
   - schedule log collection

2. Decide scheduling mechanism
   - background task in-app
   - lightweight queue
   - asynchronous fire-and-forget if acceptable

3. Make collector failure non-fatal
   - report succeeds
   - log bundle failure is logged separately

4. Optionally add a status field into report metadata
   - `logBundleScheduled`
   - `logBundleComplete`
   - `logBundleError`

### Risks

- background tasks may be interrupted by container lifecycle

### Mitigation

- if in-process background execution proves unreliable, move to a queued or
  externalized collector

## Query Strategy Details

### Required scoping

Every collector query should scope by:

- Cloud Run service name
- app environment
- session id
- time window

### Example logical filter shape

- `resource.type="cloud_run_revision"`
- `resource.labels.service_name="aimsbot-staging"`
- `timestamp >= reported_at - 20m`
- `timestamp <= reported_at + 2m`
- one of:
  - structured `sessionId`
  - text payload containing the session id

### Why not instance id

- a conversation can span multiple instances
- instance ids are operationally unstable
- users do not know them
- the primary business key is the session

## Verification Plan

### Unit tests

- request middleware extracts and logs `sessionId`
- telemetry helper uses context defaults correctly
- degraded reply paths emit the right reason codes
- collector query builder uses the correct filters
- storage path generation for `.logs.json` is correct

### Integration tests

- report flow schedules collection
- collector writes neighbor artifact next to archived session
- failure in collector does not fail report submission

### Manual validation

In staging:

1. run a session with a known `sessionId`
2. submit a bug report
3. verify:
   - session archive exists
   - log bundle exists next to it
   - collected logs are bounded to staging service/environment
   - logs include the expected request and reply-fallback events

## Rollout Strategy

### Step 1

Land logging standardization and degraded reply telemetry first.

Reason:
- improves debugging immediately
- reduces risk before building the collector

### Step 2

Land log collector behind a feature flag or environment toggle if desired.

Reason:
- makes rollout safer
- allows staging-only validation first

### Step 3

Turn on automatic collection for staging.

### Step 4

Promote to prod after verifying:

- no meaningful report latency increase
- collector success rate is acceptable
- GCS artifacts are correctly organized

## Open Design Decisions

1. Should collector execution stay in-process initially, or use a queue from
   day one?
2. Should `requestId`s discovered during session logs be used to pull in
   adjacent non-session logs automatically?
3. Should log bundles include third-party logs in the same time window, or only
   app-owned events by default?
4. Should we write one raw bundle only, or also a pre-summarized timeline file?

## Recommendation

Recommended first implementation:

1. standardize app-owned logging metadata
2. add context propagation
3. emit explicit fallback/normalization reason events
4. build an in-repo async collector keyed by:
   - `session_id`
   - `service_name`
   - `app_env`
   - bounded time window
5. write `.logs.json` next to the archived session artifact

This gives the highest practical debugging value with the least operational
complexity.
