import { describe, expect, it } from "vitest";

import type { AgentRoom } from "@/types/api";

import { toWorldAgent, toWorldAgents } from "./renderPayload";

const ALLOWED_KEYS = ["activity", "agent_id", "display_name", "floor", "room_index"];

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
    ...overrides,
  } as AgentRoom;
}

describe("world render payload allow-list (data-warden D11)", () => {
  it("exposes exactly agent_id, display_name, activity, floor and room_index", () => {
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
    });
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
