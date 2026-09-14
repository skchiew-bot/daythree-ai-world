# ADR-008: Observability

## Context

Spec §24 requires request/correlation/mission/run/model-invocation ids on every relevant
log line, plus API/mission/model/runtime/infrastructure metrics; spec §25 puts an
`otel-collector`, `prometheus`, and `grafana` in the local compose stack. The user's
chosen Phase 0 scope for this build was explicitly "lean, not polished" observability.

## Options Considered

1. **structlog (JSON) + OpenTelemetry SDK (FastAPI auto-instrumentation, traces only) +
   `prometheus_client` custom counters/histograms + one hand-written Grafana dashboard.**
2. A fully custom metrics/tracing pipeline with per-domain-event OTel spans (a span per
   checkpoint, per tool call, per budget check) and several curated Grafana dashboards.
3. Skip OpenTelemetry entirely for Phase 0 and rely on structured logs + Prometheus only.

## Decision

Option 1.

## Rationale

- `structlog`'s `contextvars` binding (`services/api/middleware/request_context.py`) is
  the simplest mechanism that satisfies spec §24's "every request carries `request_id`/
  `correlation_id`" without threading an explicit logger instance through every call —
  and it composes with spec §23's "never log secrets" requirement because nothing in the
  request-context middleware ever reads a request body or Authorization header value.
- FastAPI's built-in OpenTelemetry auto-instrumentation (`opentelemetry-instrumentation-
  fastapi`) gives one trace per HTTP request for free; hand-instrumenting every internal
  function (option 2) would be real engineering effort with no Phase 0 consumer actually
  asking "show me the trace for one specific tool call" yet.
- Nine named Prometheus counters/histograms
  (`services/observability/metrics/registry.py`) were chosen to be exactly the set the
  one Grafana dashboard (`infrastructure/compose/grafana/dashboards/phase0-overview.json`)
  actually reads — mission throughput, model cost/latency, task duration, retries/
  recoveries, budget/tool-denial events — rather than instrumenting speculatively.
- Skipping OTel entirely (option 3) would mean spec §25's `otel-collector` service in the
  compose stack has nothing to collect, and would remove the one Phase 1 on-ramp
  (traces already flowing through a collector) for when tracing actually gets used for
  debugging a real production issue.

## Consequences

- Tracing is FastAPI-request-scoped only; the worker process has no equivalent trace
  instrumentation in this Phase 0 build (it does have the same `structlog` JSON logging
  and Prometheus-exportable counters, just not OTel spans) — a reasonable next increment
  once a real cross-process trace (API request → queued task → worker execution) is
  needed.
- The Grafana dashboard is one file, six panels, provisioned automatically
  (`infrastructure/compose/grafana/provisioning/`) — functional for verifying the demo
  mission and the resilience tests produced real telemetry, not a polished multi-
  dashboard operational suite.
- `configure_tracing`'s OTLP exporter setup is wrapped in a bare `try/except` so a
  missing/unreachable collector never blocks API startup (`services/observability/
  tracing/setup.py`) — traces are best-effort, matching how spec §15 treats Redis.

## Rollback Path

Remove `configure_tracing()`'s call site in `services/api/app/main.py` to disable
tracing entirely without touching logging or metrics; the three concerns are wired
independently on purpose.
