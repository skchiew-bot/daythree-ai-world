import { describe, expect, it } from "vitest";

import type { AgentRoom } from "@/types/api";

import { toWorldAgent } from "./renderPayload";
import { describeScene } from "./sceneLabel";

function agent(activity: AgentRoom["activity"], i: number) {
  return toWorldAgent({
    agent_id: `a-${i}`,
    agent_code: `AG-${i}`,
    display_name: `Agent ${i}`,
    lifecycle_state: "active",
    floor: 1,
    room_index: 1,
    assigned_at: "2026-09-19T08:00:00Z",
    activity,
    active_task_id: null,
    activity_changed_at: null,
    project_id: null,
  });
}

describe("describeScene", () => {
  it("lists every activity and the per-activity counts add up to the total", () => {
    const activities: AgentRoom["activity"][] = ["idle", "idle", "assigned", "working", "completed", "failed", "failed"];
    const label = describeScene(activities.map(agent), 2);

    expect(label).toContain("7 governed agents");
    expect(label).toContain("2 idle, 1 assigned, 1 working, 1 completed, 2 failed");
    expect(label).toContain("2 external agents");
  });

  it("handles an empty building", () => {
    expect(describeScene([], 0)).toContain("0 governed agents (0 idle, 0 assigned, 0 working, 0 completed, 0 failed)");
  });
});
