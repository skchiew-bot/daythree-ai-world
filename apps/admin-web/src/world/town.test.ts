import { describe, expect, it } from "vitest";

import {
  buildTownPlan,
  HALL_NODE,
  LOT_COUNT,
  pathLength,
  pathPoint,
  RESIDENCE_NODE,
  shortestPath,
} from "./town";

describe("town road graph (ADR-014 decision 4)", () => {
  it("has exactly 48 lots", () => {
    expect(buildTownPlan().lots).toHaveLength(LOT_COUNT);
  });

  it("reaches every lot from the residence and the hall with a finite path", () => {
    const town = buildTownPlan();
    for (const lot of town.lots) {
      const fromResidence = shortestPath(town.roads, RESIDENCE_NODE, lot.roadNode);
      const fromHall = shortestPath(town.roads, HALL_NODE, lot.roadNode);
      expect(fromResidence).not.toBeNull();
      expect(fromHall).not.toBeNull();
      expect(pathLength(fromResidence!)).toBeGreaterThan(0);
      expect(Number.isFinite(pathLength(fromHall!))).toBe(true);
    }
  });

  it("connects the residence to the hall", () => {
    const town = buildTownPlan();
    const path = shortestPath(town.roads, RESIDENCE_NODE, HALL_NODE);
    expect(path).not.toBeNull();
    expect(Number.isFinite(pathLength(path!))).toBe(true);
  });

  it("returns null for an unknown node", () => {
    const town = buildTownPlan();
    expect(shortestPath(town.roads, RESIDENCE_NODE, "nowhere")).toBeNull();
  });

  it("gives every lot a distinct position", () => {
    const town = buildTownPlan();
    const keys = new Set(town.lots.map((l) => `${l.center.x}:${l.center.z}`));
    expect(keys.size).toBe(LOT_COUNT);
  });
});

describe("pathPoint", () => {
  it("walks a polyline in order and reports a unit direction", () => {
    const points = [
      { x: 0, z: 0 },
      { x: 10, z: 0 },
      { x: 10, z: 10 },
    ];
    expect(pathPoint(points, 0)).toMatchObject({ x: 0, z: 0 });
    expect(pathPoint(points, 5)).toMatchObject({ x: 5, z: 0 });
    expect(pathPoint(points, 10)).toMatchObject({ x: 10, z: 0 });
    const mid = pathPoint(points, 15);
    expect(mid.x).toBeCloseTo(10);
    expect(mid.z).toBeCloseTo(5);
    expect(Math.hypot(mid.dx, mid.dz)).toBeCloseTo(1);
  });

  it("clamps beyond the polyline's length", () => {
    const points = [
      { x: 0, z: 0 },
      { x: 4, z: 0 },
    ];
    expect(pathPoint(points, 100)).toMatchObject({ x: 4, z: 0 });
  });
});
