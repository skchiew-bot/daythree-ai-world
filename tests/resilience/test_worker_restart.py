"""TC-P0-007 / spec §15 "Worker crash during model call": kill the worker container
mid-task, restart it, and confirm the task recovers (or is cleanly retryable) with no
duplicate committed artifact — against the real compose stack, not a simulation.
"""
from __future__ import annotations

import subprocess
import time

import httpx
import pytest

pytestmark = pytest.mark.resilience

API_URL = "http://localhost:8000"


def _login() -> str:
    import os

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


def test_worker_kill_and_restart_recovers_the_task_without_duplicate_artifact():
    token = _login()
    headers = {"Authorization": f"Bearer {token}"}

    agents = httpx.get(f"{API_URL}/api/v1/agents", headers=headers, timeout=10).json()
    assert agents, "Seed data missing — run `make seed` before the resilience suite."
    agent_id = agents[0]["id"]

    mission = httpx.post(
        f"{API_URL}/api/v1/missions", headers=headers, timeout=10,
        json={"title": "Resilience test", "objective": "Prove worker restart recovers this task.",
              "assigned_agent_id": agent_id},
    ).json()
    mission_id = mission["id"]

    httpx.post(f"{API_URL}/api/v1/missions/{mission_id}/start", headers=headers, timeout=10)

    # Give the worker a brief moment to pick the task up, then kill it mid-flight.
    # Caveat: with the default MockModelProvider a task can finish in single-digit
    # milliseconds, so this kill may land after the task already completed rather than
    # truly mid-flight — the assertions below (exactly one task, at most one committed
    # artifact) still hold either way and remain a real regression check. For a timing-
    # sensitive proof of the crash-mid-model-call path, run with a slower/real provider
    # (`DEFAULT_MODEL_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` set) so the window is
    # wide enough to reliably land the kill during the model call.
    time.sleep(0.5)
    subprocess.run(["docker", "compose", "kill", "worker"], check=True, timeout=30)
    subprocess.run(["docker", "compose", "up", "-d", "worker"], check=True, timeout=30)

    final_status = None
    for _ in range(60):
        current = httpx.get(f"{API_URL}/api/v1/missions/{mission_id}", headers=headers, timeout=10).json()
        if current["status"] in ("completed", "failed"):
            final_status = current["status"]
            break
        time.sleep(1)

    assert final_status is not None, "Mission never reached a terminal state after worker restart."

    tasks = httpx.get(f"{API_URL}/api/v1/missions/{mission_id}/tasks", headers=headers, timeout=10).json()
    assert len(tasks) == 1  # exactly one task — recovery resumed it, it didn't spawn a duplicate

    artifacts = httpx.get(
        f"{API_URL}/api/v1/missions/{mission_id}/artifacts", headers=headers, timeout=10
    ).json()
    mission_output_artifacts = [a for a in artifacts if a["artifact_type"] == "mission_output"]
    assert len(mission_output_artifacts) <= 1  # never a duplicate committed artifact
