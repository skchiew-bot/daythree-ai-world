import { describe, expect, it } from "vitest";

import { daylightAt, tintAt } from "./dayNight";
import { hashString, seededRandom } from "./rng";
import {
  CORRIDOR_LANE_Z,
  FLOOR_HEIGHT,
  LOBBY_SPOT_XS,
  ROOM_DEPTH,
  ROOM_WIDTH,
  roomAnchors,
} from "./layout";
import { buildRoute, routePoint } from "./routes";
import { turnToward, wrapAngle } from "./agentMotion";

describe("room anchors (ADR-009)", () => {
  it("is a pure function of floor and room index", () => {
    expect(roomAnchors(3, 2)).toEqual(roomAnchors(3, 2));
  });

  it("puts rooms one ROOM_WIDTH apart and floors one FLOOR_HEIGHT apart", () => {
    const a = roomAnchors(1, 1).center;
    expect(roomAnchors(1, 2).center.x - a.x).toBeCloseTo(ROOM_WIDTH);
    expect(roomAnchors(2, 1).center.y - a.y).toBeCloseTo(FLOOR_HEIGHT);
  });

  it("keeps idle, desk and door inside the room's footprint", () => {
    const { center, idle, desk, door } = roomAnchors(1, 3);
    for (const p of [idle, desk, door]) {
      expect(Math.abs(p.x - center.x)).toBeLessThan(ROOM_WIDTH / 2);
      expect(Math.abs(p.z)).toBeLessThan(ROOM_DEPTH / 2);
    }
  });
});

describe("routes", () => {
  it("starts at the desk, passes the idle spot and ends in the corridor zone", () => {
    const route = buildRoute(2, { kind: "lobby", spot: 1 });
    const anchors = roomAnchors(1, 2);

    expect(routePoint(route, 0).x).toBeCloseTo(anchors.desk.x);
    expect(routePoint(route, route.idleS).z).toBeCloseTo(anchors.idle.z);
    expect(routePoint(route, route.laneS).z).toBeCloseTo(CORRIDOR_LANE_Z);
    expect(routePoint(route, route.length).x).toBeCloseTo(LOBBY_SPOT_XS[1]);
  });

  it("gives every destination of a room the same desk-to-lane prefix", () => {
    const lobby = buildRoute(4, { kind: "lobby", spot: 0 });
    const stroll = buildRoute(4, { kind: "strollLeft", spot: 0 });

    expect(lobby.idleS).toBeCloseTo(stroll.idleS);
    expect(lobby.laneS).toBeCloseTo(stroll.laneS);
    for (const s of [0, lobby.idleS, lobby.laneS]) {
      expect(routePoint(lobby, s).x).toBeCloseTo(routePoint(stroll, s).x);
      expect(routePoint(lobby, s).z).toBeCloseTo(routePoint(stroll, s).z);
    }
  });

  it("clamps s to the route and reports a unit direction", () => {
    const route = buildRoute(1, { kind: "strollRight", spot: 0 });
    const end = routePoint(route, route.length + 5);

    expect(end.x).toBeCloseTo(routePoint(route, route.length).x);
    expect(Math.hypot(end.dx, end.dz)).toBeCloseTo(1);
  });

  it("stays out of the other rooms while walking in the corridor", () => {
    const route = buildRoute(1, { kind: "strollRight", spot: 0 });
    for (let s = route.laneS; s <= route.length; s += 0.1) {
      expect(routePoint(route, s).z).toBeGreaterThanOrEqual(CORRIDOR_LANE_Z - 1e-9);
    }
  });
});

describe("seeded randomness", () => {
  it("returns the same sequence for the same key", () => {
    const a = seededRandom("agent|12");
    const b = seededRandom("agent|12");
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
  });

  it("differs between keys and stays in [0, 1)", () => {
    expect(hashString("a|1")).not.toBe(hashString("a|2"));
    const rng = seededRandom("range");
    for (let i = 0; i < 1000; i++) {
      const v = rng();
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });
});

describe("angles", () => {
  it("wraps into [-pi, pi)", () => {
    expect(wrapAngle(3 * Math.PI)).toBeCloseTo(-Math.PI);
    expect(wrapAngle(-0.5)).toBeCloseTo(-0.5);
  });

  it("turns the short way and never overshoots", () => {
    expect(turnToward(3, -3, 0.1)).toBeCloseTo(3.1);
    expect(turnToward(0, 0.05, 0.1)).toBeCloseTo(0.05);
  });
});

describe("day/night tint", () => {
  it("is bright at noon and dark at midnight", () => {
    expect(daylightAt(12.5)).toBe(1);
    expect(daylightAt(0)).toBe(0);
    expect(tintAt(12.5).keyIntensity).toBeGreaterThan(tintAt(0).keyIntensity);
    expect(tintAt(0).lampGlow).toBeGreaterThan(tintAt(12.5).lampGlow);
  });

  it("changes smoothly: no minute-to-minute jump anywhere in the day", () => {
    let previous = tintAt(0);
    for (let minute = 1; minute <= 24 * 60; minute++) {
      const next = tintAt(minute / 60);
      expect(Math.abs(next.daylight - previous.daylight)).toBeLessThan(0.02);
      expect(Math.abs(next.sky[0] - previous.sky[0])).toBeLessThan(0.02);
      expect(Math.abs(next.keyIntensity - previous.keyIntensity)).toBeLessThan(0.05);
      previous = next;
    }
  });

  it("joins up across midnight", () => {
    expect(tintAt(23.999).sky).toEqual(tintAt(0).sky);
  });
});
