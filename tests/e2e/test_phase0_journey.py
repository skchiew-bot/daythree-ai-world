"""The exact spec §27 E2E script: login -> create agent -> create mission -> start
mission -> wait for completion -> inspect artifact -> inspect audit timeline.

Assumes `make seed` has already run (so a model policy exists for the agent-creation
dropdown and the seeded admin credentials are valid) and the demo Atlas agent may or
may not already exist — this test creates its own agent so it's independent of that.
"""
from __future__ import annotations

import os

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

ADMIN_EMAIL = os.environ.get("SEED_ADMIN_EMAIL", "admin@daythree.local")
ADMIN_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "ChangeMe123!")
BASE_URL = "http://localhost:5173"


def test_full_phase0_journey(page: Page):
    # 1. Login
    page.goto(BASE_URL)
    page.get_by_label("Email").fill(ADMIN_EMAIL)
    page.get_by_label("Password").fill(ADMIN_PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    # Not get_by_text("Dashboard") — that matches both the nav link and the <h2>
    # heading and trips Playwright's strict-mode ambiguity check (found by CI's first
    # real run of this test). The heading role is unambiguous.
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible(timeout=10_000)

    # 2. Create agent
    page.get_by_role("link", name="Create Agent").click()
    agent_code = "AGT-E2E-001"
    page.get_by_label("Agent code").fill(agent_code)
    page.get_by_label("Name").fill("E2E Test Agent")
    page.get_by_label("System prompt").fill("You are a test agent for the Phase 0 E2E journey.")
    page.get_by_label("Model policy").select_option(index=1)  # first real option after "Select…"
    page.get_by_text("artifact.write").click()
    page.get_by_text("artifact.read").click()
    page.get_by_role("button", name="Create agent").click()
    expect(page).to_have_url(f"{BASE_URL}/agents", timeout=10_000)
    expect(page.get_by_text(agent_code)).to_be_visible()

    # 3. Create mission
    page.get_by_role("link", name="Mission Control").click()
    mission_title = "E2E Journey Mission"
    page.get_by_label("Title").fill(mission_title)
    page.get_by_label("Objective").fill("Prove the Phase 0 loop works end-to-end via the UI.")
    page.get_by_label("Assigned agent").select_option(label=f"E2E Test Agent ({agent_code})")
    page.get_by_role("button", name="Create mission").click()
    expect(page.get_by_text(mission_title)).to_be_visible(timeout=10_000)

    # 4. Start mission
    row = page.locator("tr", has_text=mission_title)
    row.get_by_role("button", name="Start").click()
    # Scoped to the status badge's own class, not get_by_text("running") — the
    # Overview tab (reached in step 5) also renders a "Started:" label, which a
    # case-insensitive substring match on "running" wouldn't hit, but being
    # consistent about targeting the badge itself avoids the same class of ambiguity
    # the "Dashboard" fix above addresses.
    expect(row.locator(".badge.status-running")).to_be_visible(timeout=10_000)

    # 5. Wait for completion
    row.get_by_role("link").first.click()
    # Not get_by_text("completed") — the Overview tab's "Completed:" label is a
    # case-insensitive substring match for "completed" too, so this would hit the
    # same strict-mode violation as step 1's original "Dashboard" locator.
    expect(page.locator(".badge.status-completed")).to_be_visible(timeout=30_000)

    # 6. Inspect artifact
    page.get_by_role("button", name="Artifact").click()
    expect(page.get_by_role("button", name="Download (signed URL)")).to_be_visible()

    # 7. Inspect audit timeline
    page.get_by_role("button", name="Timeline", exact=True).click()
    expect(page.get_by_text("task.started")).to_be_visible()
    expect(page.get_by_text("mission.completed")).to_be_visible()
