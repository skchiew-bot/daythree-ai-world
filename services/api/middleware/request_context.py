"""Binds `request_id`/`correlation_id` to every log line for the duration of a
request (spec §24) and records the two HTTP Prometheus metrics. `correlation_id` is
accepted from an incoming `X-Correlation-Id` header when present (so a caller can tie
a request to a broader operation it's already tracking) and always echoed back.
"""
from __future__ import annotations

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from observability.metrics.registry import http_request_duration_seconds, http_requests_total


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        correlation_id = request.headers.get("x-correlation-id", request_id)

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, correlation_id=correlation_id)

        start = time.monotonic()
        response = await call_next(request)
        duration = time.monotonic() - start

        route_path = request.scope.get("route").path if request.scope.get("route") else request.url.path
        http_requests_total.labels(
            method=request.method, path=route_path, status=str(response.status_code)
        ).inc()
        http_request_duration_seconds.labels(method=request.method, path=route_path).observe(duration)

        response.headers["X-Request-Id"] = request_id
        response.headers["X-Correlation-Id"] = correlation_id
        return response
