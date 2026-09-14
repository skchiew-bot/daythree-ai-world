"""JSON structured logging. Every log line can carry `request_id`/`correlation_id`/
`mission_id`/`run_id`/`model_invocation_id` via structlog's contextvars — never a
secret (spec §23: never log API keys, tokens, passwords, secret headers, raw creds).
The one deliberate discipline this module can't enforce automatically: never pass a
raw prompt, password, or Authorization header value as a log field. Call sites are
responsible for that; see `services/api/middleware/request_context.py` for the one
place headers are read.
"""
from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", level=level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
