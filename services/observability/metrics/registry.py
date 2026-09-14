"""The Prometheus metrics the Phase 0 Grafana dashboard reads. Module-level singletons
(the standard prometheus_client pattern) so both the api process (HTTP metrics) and the
worker process (mission/task/model metrics) can import and increment the same names —
`/metrics` on the api process is scraped; the worker's updates land in the same
default registry because `prometheus_client` is per-process, and Phase 0 only exposes
`/metrics` from the api process. Worker-side counters are exported via the OTel
Collector's Prometheus exporter pipeline instead (see
`infrastructure/compose/otel-collector-config.yaml`) so both processes' numbers show up
without needing a Prometheus push-gateway.
"""
from __future__ import annotations

from prometheus_client import Counter, Histogram

http_requests_total = Counter(
    "daythree_http_requests_total", "Total API requests", ["method", "path", "status"]
)
http_request_duration_seconds = Histogram(
    "daythree_http_request_duration_seconds", "API request latency", ["method", "path"]
)

missions_started_total = Counter("daythree_missions_started_total", "Missions started")
missions_completed_total = Counter("daythree_missions_completed_total", "Missions completed")
missions_failed_total = Counter("daythree_missions_failed_total", "Missions failed")

model_invocations_total = Counter(
    "daythree_model_invocations_total", "Model invocations", ["status", "provider"]
)
model_cost_usd_total = Counter("daythree_model_cost_usd_total", "Estimated model spend (USD)")

task_duration_seconds = Histogram("daythree_task_duration_seconds", "Task execution duration")
task_retries_total = Counter("daythree_task_retries_total", "Task retries")

runtime_recoveries_total = Counter(
    "daythree_runtime_recoveries_total", "Runtime resume-from-checkpoint recoveries"
)

budget_exceeded_total = Counter("daythree_budget_exceeded_total", "Budget-exceeded rejections")
tool_denied_total = Counter("daythree_tool_denied_total", "Denied tool invocation attempts")
