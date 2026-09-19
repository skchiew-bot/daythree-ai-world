import { describe, expect, it } from "vitest";

import type { AgentRoom } from "@/types/api";

import type { WorldInputs } from "./runWorld";
import { toWorldAgent, type WorldAgent } from "./renderPayload";

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
} satisfies AgentRoom;

describe("WorldAgent is only producible by toWorldAgent (data-warden D11)", () => {
  it("rejects a raw API row", () => {
    // @ts-expect-error an AgentRoom is not a WorldAgent
    const agent: WorldAgent = row;
    expect(agent).toBe(row);
  });

  it("rejects an object literal with the five allowed fields", () => {
    // @ts-expect-error only toWorldAgent may build a WorldAgent
    const agent: WorldAgent = { agent_id: "a", display_name: "A", activity: "idle", floor: 1, room_index: 1 };
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
    };
    expect(inputs.floors).toBe(5);
  });

  it("accepts what toWorldAgent returns", () => {
    const agents: WorldInputs["agents"] = [toWorldAgent(row)];
    expect(agents).toHaveLength(1);
  });
});
