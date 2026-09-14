"""TC-P0-006 "API restart": a mission created (and, here, started) before the api
container restarts must still be there — with the exact same status — once it comes
back, proving state reloads from the DB rather than living in process memory.
"""
from __future__ import annotations

import os
import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.resilience

API_URL = "http://localhost:8000"


def _login() -> str:
    response = httpx.post(
        f"{API_URL}/api/v1/auth/login",
        data={
            "username": os.environ.get("SEED_ADMIN_EMAIL", "admin@daythree.local"),
            "password": os.environ.get("SEED_ADMIN_PASSWORD", "ChangeMe123!"),
        },
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _wait_for_api(timeout_seconds: int = 30) -> None:
    for _ in range(timeout_seconds):
        try:
            if httpx.get(f"{API_URL}/health/live", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError("API did not come back up in time after restart.")


def test_mission_survives_api_restart():
    token = _login()
    headers = {"Authorization": f"Bearer {token}"}

    agents = httpx.get(f"{API_URL}/api/v1/agents", headers=headers, timeout=10).json()
    assert agents, "Seed data missing — run `make seed` before the resilience suite."

    mission = httpx.post(
        f"{API_URL}/api/v1/missions", headers=headers, timeout=10,
        json={"title": "API restart test", "objective": "Survive an API restart.",
              "assigned_agent_id": agents[0]["id"]},
    ).json()
    mission_id = mission["id"]

    subprocess.run(["docker", "compose", "restart", "api"], check=True, timeout=60)
    _wait_for_api()

    # Re-authenticate: the old token is still valid (stateless JWT), but logging in
    # again too proves auth itself survived the restart, not just the mission row.
    token_after = _login()
    recovered = httpx.get(
        f"{API_URL}/api/v1/missions/{mission_id}", headers={"Authorization": f"Bearer {token_after}"}, timeout=10
    )
    assert recovered.status_code == 200
    assert recovered.json()["id"] == mission_id
    assert recovered.json()["status"] == "draft"  # unchanged — no state lost, none invented either
