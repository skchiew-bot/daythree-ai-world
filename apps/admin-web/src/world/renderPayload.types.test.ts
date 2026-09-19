import { describe, expect, it } from "vitest";

import type { AgentRoom, ProjectSummary } from "@/types/api";

import type { WorldInputs } from "./runWorld";
import { toWorldAgent, toWorldProject, type WorldAgent, type WorldProject } from "./renderPayload";

/** These are compile-time checks. `npm run typecheck` (run in CI) fails if any
 * `@ts-expect-error` below stops being an error, i.e. if the allow-list stops being
 * enforced by the type system. */
const row = {
  agent_id: "a-1",
  agent_code: "ATLAS",
  display_name: "Atlas",
  lifecycle_state: "active",
  floor: 1,
  room_index: 1,
  assigned_at: "2026-09-19T08:00:00Z",
  activity: "idle",
  active_task_id: null,
  activity_changed_at: null,
  project_id: null,
} satisfies AgentRoom;

const projectRow = {
  id: "p-1",
  code: "ATLAS-1",
  name: "Acme Corp payroll rebuild",
  status: "active",
} satisfies ProjectSummary;

describe("WorldAgent is only producible by toWorldAgent (data-warden D11)", () => {
  it("rejects a raw API row", () => {
    // @ts-expect-error an AgentRoom is not a WorldAgent
    const agent: WorldAgent = row;
    expect(agent).toBe(row);
  });

  it("rejects an object literal with the six allowed fields", () => {
    // @ts-expect-error only toWorldAgent may build a WorldAgent
    const agent: WorldAgent = { agent_id: "a", display_name: "A", activity: "idle", floor: 1, room_index: 1, project_id: null };
    expect(agent.agent_id).toBe("a");
  });

  it("rejects raw rows in the scene inputs", () => {
    const inputs: WorldInputs = {
      // @ts-expect-error the scene does not accept raw API rows
      agents: [row],
      agentStates: new Map(),
      floors: 5,
      externalNames: [],
      externalStates: new Map(),
      projects: [],
    };
    expect(inputs.floors).toBe(5);
  });

  it("accepts what toWorldAgent returns", () => {
    const agents: WorldInputs["agents"] = [toWorldAgent(row)];
    expect(agents).toHaveLength(1);
  });
});

describe("WorldProject is only producible by toWorldProject (data-warden D13)", () => {
  it("rejects a raw ProjectSummary, which carries name", () => {
    // @ts-expect-error a ProjectSummary (with name) is not a WorldProject
    const project: WorldProject = projectRow;
    expect(project).toBe(projectRow);
  });

  it("rejects an object literal with the two allowed fields", () => {
    // @ts-expect-error only toWorldProject may build a WorldProject
    const project: WorldProject = { id: "p", code: "C" };
    expect(project.id).toBe("p");
  });

  it("rejects raw project rows in the scene inputs", () => {
    const inputs: WorldInputs = {
      agents: [],
      agentStates: new Map(),
      floors: 5,
      externalNames: [],
      externalStates: new Map(),
      // @ts-expect-error the scene does not accept raw project rows
      projects: [projectRow],
    };
    expect(inputs.projects).toHaveLength(1);
  });

  it("accepts what toWorldProject returns", () => {
    const projects: WorldInputs["projects"] = [toWorldProject(projectRow)];
    expect(projects).toHaveLength(1);
  });
});
