import { describe, expect, it } from "vitest";

import { assignLots } from "./lots";
import { buildTownPlan, type TownPlan } from "./town";
import { initCommute, isArrivedAt, placeFor, poseAt, speedOf, stepCommute, vehicleFor, type Place } from "./commute";

const town: TownPlan = buildTownPlan();
const lotOf = assignLots(["proj-a", "proj-b", "proj-c"]);

describe("placeFor (ADR-014 decision 4)", () => {
  it("puts a twin with a project at that project's building", () => {
    expect(placeFor({ activity: "working", project_id: "proj-a" })).toEqual({ kind: "project", projectId: "proj-a" });
  });

  it("keeps a twin at its project through the result-hold phase", () => {
    expect(placeFor({ activity: "completed", project_id: "proj-a" })).toEqual({ kind: "project", projectId: "proj-a" });
  });

  it("puts a working twin with no project at the hall", () => {
    expect(placeFor({ activity: "working", project_id: null })).toEqual({ kind: "hall" });
    expect(placeFor({ activity: "assigned", project_id: null })).toEqual({ kind: "hall" });
  });

  it("puts an idle twin with no project at the residence", () => {
    expect(placeFor({ activity: "idle", project_id: null })).toEqual({ kind: "residence" });
  });
});

describe("vehicleFor (ADR-014 decision 5, D15)", () => {
  it("is a pure function of distance and agent id", () => {
    expect(vehicleFor(5, "agent-1")).toBe(vehicleFor(5, "agent-1"));
  });

  it("picks walk, bicycle or motorbike as distance grows", () => {
    expect(vehicleFor(2, "agent-1")).toBe("walk");
    expect(vehicleFor(25, "agent-1")).toBe("bicycle");
    expect(vehicleFor(90, "agent-1")).toBe("motorbike");
  });

  it("never derives from anything but distance and id (no NaN, no exceptions) across many ids", () => {
    for (let i = 0; i < 50; i++) {
      const vehicle = vehicleFor(30, `agent-${i}`);
      expect(["walk", "bicycle", "motorbike"]).toContain(vehicle);
    }
  });
});

describe("stepCommute + poseAt (ADR-014 decision 4)", () => {
  it("is deterministic: the same state and time give the same position twice", () => {
    const project: Place = { kind: "project", projectId: "proj-a" };
    const start = initCommute({ kind: "residence" });
    const stepped = stepCommute(start, project, "agent-1", town, lotOf, 1_000, false);

    const a = poseAt(stepped, town, lotOf, 5_000, "agent-1");
    const b = poseAt(stepped, town, lotOf, 5_000, "agent-1");
    expect(a).toEqual(b);
  });

  it("starts walking toward a project when project_id is assigned", () => {
    const project: Place = { kind: "project", projectId: "proj-a" };
    const start = initCommute({ kind: "residence" });
    const stepped = stepCommute(start, project, "agent-1", town, lotOf, 0, false);

    expect(stepped.path).not.toBeNull();
    expect(isArrivedAt(stepped, project)).toBe(false);
  });

  it("arrives at the target after enough time has passed, without snapping instantly", () => {
    const hall: Place = { kind: "hall" };
    const start = initCommute({ kind: "residence" });
    const departed = stepCommute(start, hall, "agent-1", town, lotOf, 0, false);
    expect(isArrivedAt(departed, hall)).toBe(false);

    const travelMs = (departed.distance / speedOf(departed.vehicle)) * 1000;
    const midway = stepCommute(departed, hall, "agent-1", town, lotOf, travelMs / 2, false);
    expect(isArrivedAt(midway, hall)).toBe(false);

    const arrived = stepCommute(midway, hall, "agent-1", town, lotOf, travelMs + 1, false);
    expect(isArrivedAt(arrived, hall)).toBe(true);
  });

  it("walks home over the road graph when a project ends, rather than snapping", () => {
    const project: Place = { kind: "project", projectId: "proj-a" };
    const residence: Place = { kind: "residence" };

    let state = initCommute(project);
    state = stepCommute(state, residence, "agent-1", town, lotOf, 0, false);
    expect(state.path).not.toBeNull();

    const poseSoonAfter = poseAt(state, town, lotOf, 200, "agent-1");
    // Still en route: not yet at the residence's road node.
    const residenceNode = town.roads.nodes.get("residence")!;
    const stillTraveling = Math.hypot(poseSoonAfter.x - residenceNode.x, poseSoonAfter.z - residenceNode.z) > 0.5;
    expect(stillTraveling).toBe(true);

    const travelMs = (state.distance / speedOf(state.vehicle)) * 1000;
    const home = stepCommute(state, residence, "agent-1", town, lotOf, travelMs + 5, false);
    expect(isArrivedAt(home, residence)).toBe(true);
  });

  it("disables commuting under prefers-reduced-motion: the twin is placed at its data-driven spot with no path", () => {
    const project: Place = { kind: "project", projectId: "proj-b" };
    const start = initCommute({ kind: "residence" });
    const stepped = stepCommute(start, project, "agent-2", town, lotOf, 1_000, true);

    expect(stepped.path).toBeNull();
    expect(isArrivedAt(stepped, project)).toBe(true);
  });

  it("parks at the hall if a project somehow has no assigned lot", () => {
    const project: Place = { kind: "project", projectId: "proj-unassigned" };
    const start = initCommute({ kind: "residence" });
    const stepped = stepCommute(start, project, "agent-3", town, lotOf, 0, false);
    expect(stepped.path).not.toBeNull();
  });

  it("finishes the current walk when project_id clears mid-trip, then walks home (no snap)", () => {
    const project: Place = { kind: "project", projectId: "proj-a" };
    const residence: Place = { kind: "residence" };

    let state = stepCommute(initCommute(residence), project, "agent-1", town, lotOf, 0, false);
    const outboundPath = state.path;
    const outboundMs = (state.distance / speedOf(state.vehicle)) * 1000;

    // The task ends while the twin is still on the way out.
    state = stepCommute(state, residence, "agent-1", town, lotOf, outboundMs / 2, false);
    expect(state.path).toBe(outboundPath);
    expect(isArrivedAt(state, residence)).toBe(false);

    // The outbound trip completes at the project, it is not teleported home.
    state = stepCommute(state, residence, "agent-1", town, lotOf, outboundMs + 1, false);
    expect(isArrivedAt(state, project)).toBe(false);
    expect(state.target).toEqual(residence);
    expect(state.place).toEqual(project);
    expect(state.path).not.toBeNull();

    // Then it walks home over the road graph and only then is home.
    const homeMs = (state.distance / speedOf(state.vehicle)) * 1000;
    const home = stepCommute(state, residence, "agent-1", town, lotOf, outboundMs + 1 + homeMs + 1, false);
    expect(isArrivedAt(home, residence)).toBe(true);
  });

  it("arrives at once for a zero-length trip: hall to hall, no-lot to no-lot, then home", () => {
    const hall: Place = { kind: "hall" };
    const noLotA: Place = { kind: "project", projectId: "gone-a" };
    const noLotB: Place = { kind: "project", projectId: "gone-b" };
    const residence: Place = { kind: "residence" };

    let state = initCommute(hall);
    state = stepCommute(state, noLotA, "agent-1", town, lotOf, 0, false);
    expect(isArrivedAt(state, noLotA)).toBe(true);

    state = stepCommute(state, noLotB, "agent-1", town, lotOf, 1_000, false);
    expect(isArrivedAt(state, noLotB)).toBe(true);

    state = stepCommute(state, hall, "agent-1", town, lotOf, 2_000, false);
    expect(isArrivedAt(state, hall)).toBe(true);

    state = stepCommute(state, residence, "agent-1", town, lotOf, 3_000, false);
    expect(state.path).not.toBeNull();
    const homeMs = (state.distance / speedOf(state.vehicle)) * 1000;
    state = stepCommute(state, residence, "agent-1", town, lotOf, 3_000 + homeMs + 1, false);
    expect(isArrivedAt(state, residence)).toBe(true);
  });

  it("returns the same state object while nothing changes under reduced motion", () => {
    const project: Place = { kind: "project", projectId: "proj-a" };
    const first = stepCommute(initCommute({ kind: "residence" }), project, "agent-1", town, lotOf, 1_000, true);
    const second = stepCommute(first, project, "agent-1", town, lotOf, 2_000, true);
    expect(second).toBe(first);
  });
});
