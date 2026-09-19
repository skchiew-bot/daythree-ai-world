import { describe, expect, it } from "vitest";

import { clampToBounds, isInsideAny, OPERATOR_RADIUS_M, resolvePosition } from "./collision";
import type { Footprint } from "./footprints";

const BOX: Footprint = { key: "b", minX: -2, maxX: 2, minZ: -2, maxZ: 2 };

describe("resolvePosition (ADR-014 W3 deliverable 3, test 11)", () => {
  it("leaves a point outside every footprint untouched", () => {
    const result = resolvePosition(10, 10, [BOX]);
    expect(result).toEqual({ x: 10, z: 10 });
  });

  it("pushes a point on the edge out to the collision radius", () => {
    const result = resolvePosition(0, 2, [BOX]);
    expect(result.z).toBeCloseTo(2 + OPERATOR_RADIUS_M, 5);
    expect(isInsideAny(result.x, result.z, [BOX])).toBe(false);
  });

  it("pushes a point whose center lands inside the rectangle out through the nearest wall (W3-F6)", () => {
    const result = resolvePosition(1.9, 0, [BOX]);
    expect(isInsideAny(result.x, result.z, [BOX])).toBe(false);
    // Nearest wall from (1.9, 0) is the +x wall.
    expect(result.x).toBeGreaterThan(2);
  });

  it("clears a point out of every footprint in the list, not only the first", () => {
    const boxes: Footprint[] = [BOX, { key: "c", minX: 4, maxX: 8, minZ: -2, maxZ: 2 }];
    const result = resolvePosition(1.9, 0, boxes);
    expect(isInsideAny(result.x, result.z, boxes)).toBe(false);
  });
});

describe("clampToBounds", () => {
  it("keeps a point inside the bounds unchanged", () => {
    expect(clampToBounds(0, 0, { minX: -10, maxX: 10, minZ: -10, maxZ: 10 })).toEqual({ x: 0, z: 0 });
  });

  it("clamps a point outside the bounds to the edge", () => {
    expect(clampToBounds(50, -50, { minX: -10, maxX: 10, minZ: -10, maxZ: 10 })).toEqual({ x: 10, z: -10 });
  });
});
