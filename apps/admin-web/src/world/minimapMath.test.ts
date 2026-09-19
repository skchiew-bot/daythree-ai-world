import { describe, expect, it } from "vitest";

import type { Bounds } from "./footprints";
import { canvasToWorld, minimapSummary, nearestDot, nearestStreetLabel, worldToCanvas } from "./minimapMath";
import { streetZ } from "./town";

const BOUNDS: Bounds = { minX: -10, maxX: 10, minZ: -10, maxZ: 10 };

describe("worldToCanvas / canvasToWorld (ADR-014 W3 deliverable 7)", () => {
  it("maps the bounds center to the canvas center", () => {
    const p = worldToCanvas(0, 0, BOUNDS, 100);
    expect(p.x).toBeCloseTo(50, 5);
    expect(p.y).toBeCloseTo(50, 5);
  });

  it("round-trips a world point through canvas coordinates", () => {
    const canvasPoint = worldToCanvas(3, -4, BOUNDS, 100);
    const world = canvasToWorld(canvasPoint.x, canvasPoint.y, BOUNDS, 100);
    expect(world.x).toBeCloseTo(3, 5);
    expect(world.z).toBeCloseTo(-4, 5);
  });
});

describe("nearestDot", () => {
  it("finds the closest dot within range", () => {
    const dots = [{ x: 0, y: 0 }, { x: 50, y: 50 }];
    expect(nearestDot(1, 1, dots)).toBe(0);
  });

  it("returns null when nothing is within range", () => {
    expect(nearestDot(0, 0, [{ x: 50, y: 50 }])).toBeNull();
  });
});

describe("nearestStreetLabel (C8)", () => {
  it("names the street whose spine is closest to the given z", () => {
    expect(nearestStreetLabel(streetZ(2))).toBe("Street 3");
  });
});

describe("minimapSummary (C8 text alternative)", () => {
  it("lists building codes, the twin count and the street, and nothing else per-twin", () => {
    const text = minimapSummary({ buildingCodes: ["ATLAS-1", "ATLAS-2"], twinCount: 5, street: "Street 2" });
    expect(text).toContain("ATLAS-1, ATLAS-2");
    expect(text).toContain("Twins in town: 5");
    expect(text).toContain("Street 2");
  });

  it("says 'none yet' rather than an empty list", () => {
    expect(minimapSummary({ buildingCodes: [], twinCount: 0, street: "Street 1" })).toContain("none yet");
  });
});
