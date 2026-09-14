"""Resilience tests exercise the real `docker compose` stack by killing/restarting
actual containers — they need Docker AND the stack already up (`docker compose up
-d`), which is a stronger precondition than the integration suite's testcontainers
(those spin up their own throwaway Postgres/Redis). Skipped with a clear reason if
either isn't true.
"""
from __future__ import annotations

import subprocess

import pytest


def _compose_stack_is_up() -> bool:
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--status", "running", "--format", "{{.Service}}"],
            capture_output=True, text=True, timeout=10,
        )
        running = set(result.stdout.split())
        return {"api", "worker", "postgres", "redis"}.issubset(running)
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def _require_running_compose_stack():
    if not _compose_stack_is_up():
        pytest.skip(
            "Resilience suite requires `docker compose up -d` already running with at "
            "least api/worker/postgres/redis in the 'running' state."
        )
