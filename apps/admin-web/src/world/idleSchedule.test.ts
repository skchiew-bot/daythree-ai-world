import { describe, expect, it } from "vitest";

import { BUCKET_MS, cachedPlan, idleReference, planTrip, referenceFromPlan } from "./idleSchedule";
import { LOBBY_SPOT_XS } from "./layout";
import { buildRoute, routePoint } from "./routes";

const T0 = Date.UTC(2026, 8, 19, 10, 0, 0);
const AGENTS = ["agent-a", "agent-b", "agent-c"];

describe("memoized trip plans", () => {
  it("gives exactly the result of an uncached plan, with agents and buckets interleaved", () => {
    for (let ms = T0; ms < T0 + 15 * 60_000; ms += 1_700) {
      const bucket = Math.floor(ms / BUCKET_MS);
      for (const [i, id] of AGENTS.entries()) {
        const room = (i % 4) + 1;
        const fresh = referenceFromPlan(planTrip(id, 2, room, bucket), bucket, ms);
        expect(idleReference(id, 2, room, ms)).toEqual(fresh);
      }
    }
  });

  it("reuses the plan within a bucket and replaces it in the next", () => {
    const bucket = Math.floor(T0 / BUCKET_MS);
    const first = cachedPlan("agent-x", 1, 1, bucket);

    expect(cachedPlan("agent-x", 1, 1, bucket)).toBe(first);
    expect(cachedPlan("agent-x", 1, 1, bucket + 1)).not.toBe(first);
    expect(cachedPlan("agent-x", 1, 1, bucket + 1)).toEqual(planTrip("agent-x", 1, 1, bucket + 1));
  });

  it("replans when the room changes (reassignment)", () => {
    const bucket = Math.floor(T0 / BUCKET_MS);
    const before = cachedPlan("agent-y", 1, 1, bucket);
    const after = cachedPlan("agent-y", 1, 3, bucket);

    expect(after.route.key).not.toBe(before.route.key);
    expect(after).toEqual(planTrip("agent-y", 1, 3, bucket));
  });

  it("stays correct when more agents than the cache holds pass through", () => {
    const bucket = Math.floor(T0 / BUCKET_MS);
    for (let i = 0; i < 1200; i++) {
      const id = `bulk-${i}`;
      expect(cachedPlan(id, 1, 1, bucket)).toEqual(planTrip(id, 1, 1, bucket));
    }
  });
});

describe("room index outside 1..4", () => {
  it("still picks a real lobby spot and finite positions", () => {
    const bucket = Math.floor(T0 / BUCKET_MS);
    for (const room of [0, -3, 9, 2.6, Number.NaN]) {
      for (let b = 0; b < 40; b++) {
        const plan = planTrip("agent-edge", 1, room, bucket + b);
        const end = routePoint(plan.route, plan.route.length);

        expect(Number.isFinite(plan.route.length)).toBe(true);
        expect(Number.isFinite(plan.totalMs)).toBe(true);
        if (plan.route.key.includes("lobby")) expect(LOBBY_SPOT_XS).toContain(end.x);
      }
    }
  });

  it("wraps a negative lobby spot instead of reading LOBBY_SPOT_XS[-1]", () => {
    const route = buildRoute(2, { kind: "lobby", spot: -1 });

    expect(Number.isFinite(routePoint(route, route.length).x)).toBe(true);
    expect(LOBBY_SPOT_XS).toContain(routePoint(route, route.length).x);
  });
});
