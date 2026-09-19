import { describe, expect, it } from "vitest";

import type { Door } from "./footprints";
import { nearestDoor, PROXIMITY_RADIUS_M } from "./proximity";

const DOORS: Door[] = [
  { key: "p-1", x: 0, z: 0 },
  { key: "p-2", x: 20, z: 20 },
];

describe("nearestDoor (ADR-014 W3 deliverable 4)", () => {
  it("returns null when nothing is within range", () => {
    expect(nearestDoor(100, 100, DOORS)).toBeNull();
  });

  it("returns the door within the proximity radius", () => {
    const result = nearestDoor(1, 0, DOORS);
    expect(result?.key).toBe("p-1");
  });

  it("returns the closest of two doors both in range", () => {
    const doors: Door[] = [
      { key: "near", x: 1, z: 0 },
      { key: "far", x: 2.5, z: 0 },
    ];
    expect(nearestDoor(0, 0, doors)?.key).toBe("near");
  });

  it("treats exactly the radius as in range and just past it as out of range", () => {
    const doors: Door[] = [{ key: "edge", x: PROXIMITY_RADIUS_M, z: 0 }];
    expect(nearestDoor(0, 0, doors)?.key).toBe("edge");
    expect(nearestDoor(0, 0, [{ key: "past", x: PROXIMITY_RADIUS_M + 0.01, z: 0 }])).toBeNull();
  });
});
