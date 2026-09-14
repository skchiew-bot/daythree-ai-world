"""OpenTelemetry wiring: traces for every FastAPI request, exported to the collector
configured at `OTEL_EXPORTER_OTLP_ENDPOINT`. Kept to the FastAPI auto-instrumentation
plus a resource name — no custom spans in Phase 0 beyond what the framework gives for
free, per the user's chosen "lean, not polished" observability scope.
"""
from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing(app: FastAPI, *, service_name: str, otlp_endpoint: str) -> None:
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    try:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    except Exception:  # noqa: BLE001 — tracing must never block API startup
        pass
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
