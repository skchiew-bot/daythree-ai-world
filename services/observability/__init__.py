"""Structured logging, tracing, and metrics shared by the api and worker processes.

Kept lean per Phase 0 scope: JSON logs with request/correlation ids bound in, OTel
traces/metrics exported to the collector, and the handful of Prometheus counters the
Grafana dashboard in `infrastructure/compose/grafana/dashboards/` actually reads.
"""
