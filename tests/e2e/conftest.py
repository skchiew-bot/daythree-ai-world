"""E2E fixtures. These tests drive the real admin-web UI against a real API, so they
need the full `docker compose up` stack (or `make admin-web` + `make api` +
`make worker` run locally) — skipped with a clear reason if the admin-web origin
isn't reachable, per the same "no silent pass" rule as the integration suite.
"""
from __future__ import annotations

import urllib.request

import pytest

ADMIN_WEB_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"


def _reachable(url: str, timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def _require_full_stack():
    if not (_reachable(ADMIN_WEB_URL) and _reachable(f"{API_URL}/health/live")):
        pytest.skip(
            "E2E suite requires the full stack running (`docker compose up -d` or "
            "`make api` + `make worker` + `make admin-web`) — admin-web and/or the API "
            "were not reachable."
        )
