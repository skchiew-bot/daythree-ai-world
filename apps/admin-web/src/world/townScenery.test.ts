import { describe, expect, it } from "vitest";

import { buildTownPlan, type Vec2 } from "./town";
import { streetFurniture } from "./townScenery";

function distanceToSegment(p: Vec2, a: Vec2, b: Vec2): number {
  const dx = b.x - a.x;
  const dz = b.z - a.z;
  const lenSq = dx * dx + dz * dz;
  const t = lenSq === 0 ? 0 : Math.min(Math.max(((p.x - a.x) * dx + (p.z - a.z) * dz) / lenSq, 0), 1);
  return Math.hypot(p.x - (a.x + t * dx), p.z - (a.z + t * dz));
}

describe("street furniture (lamps and trees)", () => {
  it("never stands within 0.6 m of a road segment, so no commuter rides through one", () => {
    const { roads } = buildTownPlan();
    const segments: [Vec2, Vec2][] = [];
    for (const [from, list] of roads.edges) {
      for (const { to } of list) segments.push([roads.nodes.get(from)!, roads.nodes.get(to)!]);
    }

    const items = streetFurniture();
    expect(items.length).toBeGreaterThan(0);
    for (const item of items) {
      for (const [a, b] of segments) {
        expect(distanceToSegment(item, a, b), `${item.kind} at ${item.x},${item.z}`).toBeGreaterThan(0.6);
      }
    }
  });

  it("is deterministic", () => {
    expect(streetFurniture()).toEqual(streetFurniture());
  });
});
