import { describe, expect, it } from "vitest";

import type { Footprint } from "./footprints";
import { armLength, walkCameraPose, WALK_ARM_LENGTH_M } from "./springArm";

const WALL: Footprint = { key: "wall", minX: -1, maxX: 1, minZ: 1, maxZ: 3 };

describe("armLength (ADR-014 W3 deliverable 3, test 4)", () => {
  it("returns the full length when nothing is in the way", () => {
    expect(armLength({ x: 0, z: 0, dirX: 1, dirZ: 0 }, [], 4.5)).toBe(4.5);
  });

  it("pulls in short of a wall behind the operator", () => {
    const len = armLength({ x: 0, z: 0, dirX: 0, dirZ: 1 }, [WALL], 4.5);
    expect(len).toBeLessThan(1);
    expect(len).toBeGreaterThanOrEqual(0);
  });
});

describe("walkCameraPose (test 4: camera position after a frame equals the spring-arm output)", () => {
  it("places the camera behind the operator's heading, above ground, looking at the operator", () => {
    const pose = walkCameraPose({ x: 5, z: 5, heading: 0 }, []);
    expect(pose.x).toBeCloseTo(5, 5);
    expect(pose.z).toBeCloseTo(5 - WALK_ARM_LENGTH_M, 5);
    expect(pose.y).toBeGreaterThan(0);
    expect(pose.lookX).toBe(5);
    expect(pose.lookZ).toBe(5);
  });

  it("is a pure function: the same inputs give the same output", () => {
    const a = walkCameraPose({ x: 1, z: 2, heading: 1.2 }, [WALL]);
    const b = walkCameraPose({ x: 1, z: 2, heading: 1.2 }, [WALL]);
    expect(a).toEqual(b);
  });

  it("shortens the arm when a wall sits behind the operator", () => {
    const clipped = walkCameraPose({ x: 0, z: 0, heading: Math.PI }, [WALL]);
    const clear = walkCameraPose({ x: 0, z: 0, heading: Math.PI }, []);
    const clippedDist = Math.hypot(clipped.x, clipped.z);
    const clearDist = Math.hypot(clear.x, clear.z);
    expect(clippedDist).toBeLessThan(clearDist);
  });
});
