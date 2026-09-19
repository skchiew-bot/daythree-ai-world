import { describe, expect, it } from "vitest";

import { WALK_SPEED } from "./idleSchedule";
import { isMoving, NO_KEYS, RUN_MULTIPLIER, stepWalk, type WalkState } from "./walkMotion";

const ORIGIN: WalkState = { x: 0, z: 0, heading: 0 };

describe("stepWalk (ADR-014 W3 deliverable 3, test 11: frame-rate independent)", () => {
  it("does not move when no key is held", () => {
    const result = stepWalk(ORIGIN, NO_KEYS, 0, 0.5);
    expect(result).toEqual({ x: 0, z: 0, heading: 0 });
  });

  it("moves forward along +z at heading 0, at WALK_SPEED m/s", () => {
    const result = stepWalk(ORIGIN, { ...NO_KEYS, forward: true }, 0, 1);
    expect(result.x).toBeCloseTo(0, 5);
    expect(result.z).toBeCloseTo(WALK_SPEED, 5);
  });

  it("runs at RUN_MULTIPLIER times the walking speed", () => {
    const walked = stepWalk(ORIGIN, { ...NO_KEYS, forward: true }, 0, 1);
    const ran = stepWalk(ORIGIN, { ...NO_KEYS, forward: true, running: true }, 0, 1);
    expect(ran.z).toBeCloseTo(walked.z * RUN_MULTIPLIER, 5);
  });

  it("covers the same ground over many small steps as one large step (frame-rate independence)", () => {
    let small: WalkState = ORIGIN;
    for (let i = 0; i < 100; i++) small = stepWalk(small, { ...NO_KEYS, forward: true }, 0, 0.01);
    const large = stepWalk(ORIGIN, { ...NO_KEYS, forward: true }, 0, 1);
    expect(small.z).toBeCloseTo(large.z, 5);
  });

  it("applies the drag heading delta before moving", () => {
    const result = stepWalk(ORIGIN, { ...NO_KEYS, forward: true }, Math.PI / 2, 1);
    expect(result.heading).toBeCloseTo(Math.PI / 2, 5);
    expect(result.x).toBeCloseTo(WALK_SPEED, 5);
    expect(result.z).toBeCloseTo(0, 5);
  });

  it("strafes left and right perpendicular to heading without turning", () => {
    const left = stepWalk(ORIGIN, { ...NO_KEYS, left: true }, 0, 1);
    const right = stepWalk(ORIGIN, { ...NO_KEYS, right: true }, 0, 1);
    expect(left.heading).toBe(0);
    expect(right.heading).toBe(0);
    expect(left.x).toBeCloseTo(-right.x, 5);
  });
});

describe("isMoving", () => {
  it("is false when nothing is held and true when any direction is", () => {
    expect(isMoving(NO_KEYS)).toBe(false);
    expect(isMoving({ ...NO_KEYS, forward: true })).toBe(true);
  });
});
