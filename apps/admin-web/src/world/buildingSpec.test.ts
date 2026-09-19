import { describe, expect, it } from "vitest";

import { buildingHeight, buildingSpec, PALETTE_COUNT, ROOF_STYLES } from "./buildingSpec";
import { LOT_WIDTH } from "./town";

describe("buildingSpec (ADR-014 decision 5, D15)", () => {
  it("is a pure function of project id and lot", () => {
    expect(buildingSpec("p-1", 7)).toEqual(buildingSpec("p-1", 7));
  });

  it("stays inside the lot and within the palette and roof sets for many ids", () => {
    for (let i = 0; i < 200; i++) {
      const spec = buildingSpec(`project-${i}`, i % 48);
      expect(spec.width).toBeLessThanOrEqual(LOT_WIDTH);
      expect(spec.depth).toBeLessThanOrEqual(LOT_WIDTH);
      expect(spec.floors).toBeGreaterThanOrEqual(2);
      expect(spec.palette).toBeGreaterThanOrEqual(0);
      expect(spec.palette).toBeLessThan(PALETTE_COUNT);
      expect(ROOF_STYLES).toContain(spec.roof);
      expect(buildingHeight(spec)).toBeGreaterThan(0);
    }
  });

  it("varies across ids, so the town does not read as one repeated block", () => {
    const heights = new Set<number>();
    const roofs = new Set<string>();
    for (let i = 0; i < 60; i++) {
      const spec = buildingSpec(`project-${i}`, i);
      heights.add(spec.floors);
      roofs.add(spec.roof);
    }
    expect(heights.size).toBeGreaterThan(1);
    expect(roofs.size).toBeGreaterThan(1);
  });

  it("takes exactly two inputs: nothing about a project's code, name, status or spend can reach it", () => {
    expect(buildingSpec.length).toBe(2);
  });
});
