import { describe, expect, it } from "vitest";

import type { AgentRoom, ProjectSummary } from "@/types/api";

import { toWorldAgent, toWorldAgents, toWorldProject, toWorldProjects } from "./renderPayload";

const ALLOWED_KEYS = ["activity", "agent_id", "display_name", "floor", "project_id", "room_index"];
const ALLOWED_PROJECT_KEYS = ["code", "id"];

function apiRow(overrides: Record<string, unknown> = {}): AgentRoom {
  return {
    agent_id: "a-1",
    agent_code: "ATLAS",
    display_name: "Atlas",
    lifecycle_state: "active",
    floor: 2,
    room_index: 3,
    assigned_at: "2026-09-19T08:00:00Z",
    activity: "working",
    active_task_id: "task-secret-id",
    activity_changed_at: "2026-09-19T08:05:00Z",
    project_id: "p-1",
    ...overrides,
  } as AgentRoom;
}

function projectRow(overrides: Record<string, unknown> = {}): ProjectSummary {
  return { id: "p-1", code: "ATLAS-1", name: "Acme Corp payroll rebuild", status: "active", ...overrides };
}

describe("world render payload allow-list (data-warden D11)", () => {
  it("exposes exactly agent_id, display_name, activity, floor, room_index and project_id", () => {
    const agent = toWorldAgent(apiRow());

    expect(Object.keys(agent).sort()).toEqual(ALLOWED_KEYS);
  });

  it("copies the allowed values unchanged", () => {
    expect(toWorldAgent(apiRow())).toEqual({
      agent_id: "a-1",
      display_name: "Atlas",
      activity: "working",
      floor: 2,
      room_index: 3,
      project_id: "p-1",
    });
  });

  it("carries a null project_id through", () => {
    expect(toWorldAgent(apiRow({ project_id: null })).project_id).toBeNull();
  });

  it("drops fields the API adds later, including free text", () => {
    const hostile = apiRow({
      task_title: "Reconcile Q3 payroll",
      mission_objective: "Find the leak",
      error: "Traceback (most recent call last)",
      reason: "budget exceeded",
      note: "twin-authored note text",
      job_description: "secret job",
    });

    const agent = toWorldAgent(hostile);

    expect(Object.keys(agent).sort()).toEqual(ALLOWED_KEYS);
    expect(JSON.stringify(agent)).not.toMatch(/payroll|leak|Traceback|budget|note text|secret job|task-secret-id/);
  });

  it("maps every row and keeps the allow-list on each", () => {
    const agents = toWorldAgents([apiRow(), apiRow({ agent_id: "a-2", floor: 1, room_index: 1 })]);

    expect(agents).toHaveLength(2);
    for (const agent of agents) expect(Object.keys(agent).sort()).toEqual(ALLOWED_KEYS);
  });
});

describe("world project payload allow-list (data-warden D13)", () => {
  it("exposes exactly id and code", () => {
    expect(Object.keys(toWorldProject(projectRow())).sort()).toEqual(ALLOWED_PROJECT_KEYS);
  });

  it("copies id and code unchanged and drops name and status", () => {
    const project = toWorldProject(projectRow());

    expect(project).toEqual({ id: "p-1", code: "ATLAS-1" });
    expect(JSON.stringify(project)).not.toMatch(/Acme|payroll|active/);
  });

  it("drops extra fields the API adds later", () => {
    const project = toWorldProject(projectRow({ client: "Acme Corp", budget_usd: 90000 }));

    expect(Object.keys(project).sort()).toEqual(ALLOWED_PROJECT_KEYS);
    expect(JSON.stringify(project)).not.toMatch(/Acme|90000/);
  });

  it("maps every row and keeps the allow-list on each", () => {
    const projects = toWorldProjects([projectRow(), projectRow({ id: "p-2", code: "B" })]);

    expect(projects).toHaveLength(2);
    for (const project of projects) expect(Object.keys(project).sort()).toEqual(ALLOWED_PROJECT_KEYS);
  });
});
