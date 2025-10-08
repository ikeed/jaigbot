# Telemetry and observability (deferred)

Status: Deferred — not in scope for the current implementation phase. Basic application logging (invalid JSON, retries, fallback usage, advice-rewrite events) remains in scope and will be covered by tests.

Why deferred
- Focus on correctness and robustness of AIMS coaching flow first (classification, scoring, fallback, Redis session state).
- Avoid premature coupling to metrics systems while interfaces are still evolving.

Target metrics for a future phase
- Single-pass success rate: fraction of turns with valid JSON envelope without retry.
- Retry rate and fallback rate: fraction of turns requiring 1 retry; fraction that invoked deterministic fallback.
- Step distribution and average scores: counts per AIMS step; mean/median per-step scores.
- Overall session outcomes: coverage of required steps (Mirror/Inquire presence; Secure by end), overall score.
- Safety events: number of advice-like outputs rewritten or blocked.
- Latency and token usage: p50/p95 turn latency; prompt/response token counts (if available from SDK).

Collection approach (to be designed later)
- Structured JSON logs emitted by the backend (one log line per turn) with fields:
  - sessionId, turnIndex, modelId
  - step, score, reasons, tipsCount
  - jsonValid (bool), retryUsed (bool), fallbackUsed (bool)
  - safetyRewrite (bool)
  - latencyMs
- Optional export to a metrics backend (e.g., Cloud Logging → BigQuery or Prometheus) in a later iteration.

Acceptance criteria (when picked up)
- Unit tests cover the logging hooks (caplog) for all key events.
- A sample notebook or simple script demonstrates parsing logs to compute the target metrics.
- Documentation updated with enablement instructions and data retention considerations.
