import { describe, expect, it } from "vitest";

import { initMotion, poseOf, stepMotion, type MotionContext, type MotionState, type TravelPhase } from "./agentMotion";
import type { AgentState } from "./agentState";
import { BUCKET_MS, idleReference, planTrip } from "./idleSchedule";
import { ROOM_DEPTH, roomAnchors } from "./layout";

const AGENT = "3f2c9a52-7d1e-4b6a-9c0e-aaaa00000001";
const T0 = Date.UTC(2026, 8, 19, 10, 0, 0);

function ctx(over: Partial<MotionContext> = {}): MotionContext {
  return { agentId: AGENT, floor: 2, roomIndex: 3, state: "idle", nowMs: T0, reducedMotion: false, ...over };
}

interface Run {
  state: MotionState;
  frames: ReturnType<typeof poseOf>[];
}

/** Steps the motion model in fixed frames, like the render loop does. */
function simulate(
  start: MotionState,
  fromMs: number,
  seconds: number,
  base: Partial<MotionContext> = {},
  fps = 30,
): Run {
  let state = start;
  const frames = [];
  const dt = 1 / fps;
  for (let i = 1; i <= seconds * fps; i++) {
    state = stepMotion(state, ctx({ ...base, nowMs: fromMs + i * dt * 1000 }), dt);
    frames.push(poseOf(state));
  }
  return { state, frames };
}

function firstMomentWhere(pred: (ref: ReturnType<typeof idleReference>) => boolean, agentId = AGENT): number {
  for (let ms = T0; ms < T0 + 30 * 60_000; ms += 500) {
    if (pred(idleReference(agentId, 2, 3, ms))) return ms;
  }
  throw new Error("no matching moment in 30 minutes");
}

const atLobby = (ref: ReturnType<typeof idleReference>) => ref.s === ref.route.length;

describe("idle wandering", () => {
  it("leaves the room, walks the corridor, dwells in the lobby and comes back", () => {
    const { frames } = simulate(initMotion(ctx()), T0, 600);
    const phases = new Set<TravelPhase>(frames.map((f) => f.phase));

    for (const phase of ["room", "leave", "corridor", "lobby", "return"] as TravelPhase[]) {
      expect(phases.has(phase)).toBe(true);
    }
    expect(Math.max(...frames.map((f) => f.z))).toBeGreaterThan(ROOM_DEPTH / 2);
    expect(frames.some((f) => f.walking)).toBe(true);
  });

  it("is back inside the room between trips", () => {
    const { frames } = simulate(initMotion(ctx()), T0, 600);
    const idle = roomAnchors(2, 3).idle;
    const home = frames.filter((f) => f.phase === "room" && !f.walking);

    expect(home.length).toBeGreaterThan(50);
    for (const f of home) {
      expect(f.x).toBeCloseTo(idle.x, 2);
      expect(f.z).toBeCloseTo(idle.z, 2);
    }
  });

  it("walks at a human pace and never teleports", () => {
    const { frames } = simulate(initMotion(ctx()), T0, 600, {}, 30);
    for (let i = 1; i < frames.length; i++) {
      const jump = Math.hypot(frames[i].x - frames[i - 1].x, frames[i].z - frames[i - 1].z);
      expect(jump).toBeLessThan(0.1);
    }
  });

  it("faces the direction it walks", () => {
    const { frames } = simulate(initMotion(ctx()), T0, 600);
    let walking = 0;
    let facingForward = 0;
    for (let i = 1; i < frames.length; i++) {
      if (!frames[i].walking) continue;
      const vx = frames[i].x - frames[i - 1].x;
      const vz = frames[i].z - frames[i - 1].z;
      walking++;
      if (Math.sin(frames[i].heading) * vx + Math.cos(frames[i].heading) * vz > 0) facingForward++;
    }
    expect(walking).toBeGreaterThan(100);
    expect(facingForward / walking).toBeGreaterThan(0.9);
  });

  it("staggers agents: different ids do not share a start time", () => {
    const ids = ["agent-a", "agent-b", "agent-c", "agent-d"];
    const bucket = Math.floor(T0 / BUCKET_MS);
    const starts = ids.map((id) => planTrip(id, 2, 3, bucket).startMs);

    expect(new Set(starts).size).toBe(ids.length);
  });

  it("makes most buckets a trip so idle agents are seen moving", () => {
    const bucket = Math.floor(T0 / BUCKET_MS);
    const trips = Array.from({ length: 200 }, (_, i) => planTrip(AGENT, 2, 3, bucket + i).goes);

    expect(trips.filter(Boolean).length).toBeGreaterThan(160);
  });

  it("finishes every trip inside its bucket", () => {
    const bucket = Math.floor(T0 / BUCKET_MS);
    for (let i = 0; i < 200; i++) {
      for (const roomIndex of [1, 2, 3, 4]) {
        const plan = planTrip(AGENT, 1, roomIndex, bucket + i);
        expect(plan.startMs + plan.totalMs).toBeLessThanOrEqual(BUCKET_MS + 1e-6);
      }
    }
  });
});

describe("assigned and working agents", () => {
  it("walks home from the lobby and stays at the desk once assigned", () => {
    const at = firstMomentWhere(atLobby);
    const start = initMotion(ctx({ nowMs: at }));
    expect(poseOf(start).phase).toBe("lobby");

    const { frames, state } = simulate(start, at, 60, { state: "assigned" });
    const desk = roomAnchors(2, 3).desk;

    expect(frames.some((f) => f.walking)).toBe(true);
    expect(poseOf(state).x).toBeCloseTo(desk.x, 5);
    expect(poseOf(state).z).toBeCloseTo(desk.z, 5);
    expect(poseOf(state).atDesk).toBe(true);
    expect(poseOf(state).walking).toBe(false);
  });

  it("only ever moves towards the desk on the way home", () => {
    const at = firstMomentWhere(atLobby);
    let state = initMotion(ctx({ nowMs: at }));
    let previous = state.s;
    for (let i = 1; i <= 30 * 30; i++) {
      state = stepMotion(state, ctx({ state: "assigned", nowMs: at + (i * 1000) / 30 }), 1 / 30);
      expect(state.s).toBeLessThanOrEqual(previous + 1e-9);
      previous = state.s;
    }
  });

  it("stays at the desk for as long as the agent is working", () => {
    const desk = roomAnchors(2, 3).desk;
    const { frames } = simulate(initMotion(ctx({ state: "working" })), T0, 600, { state: "working" });

    for (const f of frames) {
      expect(f.x).toBeCloseTo(desk.x, 9);
      expect(f.z).toBeCloseTo(desk.z, 9);
      expect(f.walking).toBe(false);
    }
  });

  it("keeps completed and failed agents at the desk for the result hold", () => {
    const desk = roomAnchors(2, 3).desk;
    for (const state of ["completed", "failed", "thinking"] as AgentState[]) {
      const { frames } = simulate(initMotion(ctx({ state })), T0, 30, { state });
      expect(frames.every((f) => Math.abs(f.x - desk.x) < 1e-9 && Math.abs(f.z - desk.z) < 1e-9)).toBe(true);
    }
  });

  it("gets up and walks to its idle spot when work ends", () => {
    const { frames } = simulate(initMotion(ctx({ state: "working" })), T0, 5, { state: "idle" });

    expect(frames[0].atDesk).toBe(false);
    expect(frames.some((f) => f.walking)).toBe(true);
  });
});

describe("room reassignment (ADR-009)", () => {
  it("snaps to the new room in one frame instead of walking there", () => {
    const at = firstMomentWhere(atLobby);
    const before = initMotion(ctx({ nowMs: at }));
    const from = poseOf(before);

    const moved = ctx({ floor: 2, roomIndex: 1, nowMs: at + 33 });
    const after = stepMotion(before, moved, 1 / 30);
    const to = poseOf(after);

    expect(after).toEqual(initMotion(moved));
    expect(Math.hypot(to.x - from.x, to.z - from.z)).toBeGreaterThan(1);
    expect(after.velocity).toBe(0);
  });

  it("puts a working agent straight on the new room's desk", () => {
    const before = initMotion(ctx({ state: "working" }));
    const after = stepMotion(before, ctx({ state: "working", floor: 5, roomIndex: 2 }), 1 / 60);
    const desk = roomAnchors(5, 2).desk;

    expect(poseOf(after).x).toBeCloseTo(desk.x);
    expect(poseOf(after).z).toBeCloseTo(desk.z);
  });
});

describe("prefers-reduced-motion", () => {
  it("keeps an idle agent in its room and never walks", () => {
    const idle = roomAnchors(2, 3).idle;
    const { frames } = simulate(initMotion(ctx({ reducedMotion: true })), T0, 600, { reducedMotion: true });

    for (const f of frames) {
      expect(f.x).toBeCloseTo(idle.x, 9);
      expect(f.z).toBeCloseTo(idle.z, 9);
      expect(f.walking).toBe(false);
      expect(f.speed).toBe(0);
    }
  });

  it("brings an agent that is out wandering back into its room at once", () => {
    const at = firstMomentWhere(atLobby);
    const out = initMotion(ctx({ nowMs: at }));
    const idle = roomAnchors(2, 3).idle;

    const after = poseOf(stepMotion(out, ctx({ nowMs: at + 33, reducedMotion: true }), 1 / 30));

    expect(after.x).toBeCloseTo(idle.x);
    expect(after.z).toBeCloseTo(idle.z);
    expect(after.walking).toBe(false);
  });

  it("does not animate the desk-to-idle move either", () => {
    const after = stepMotion(initMotion(ctx({ state: "working" })), ctx({ reducedMotion: true }), 1 / 60);
    const idle = roomAnchors(2, 3).idle;

    expect(poseOf(after).x).toBeCloseTo(idle.x);
    expect(poseOf(after).walking).toBe(false);
  });
});

describe("determinism across clients", () => {
  it("gives the same position twice for the same seed and time", () => {
    const at = firstMomentWhere((ref) => ref.s > ref.route.idleS && ref.s < ref.route.length);

    expect(idleReference(AGENT, 2, 3, at)).toEqual(idleReference(AGENT, 2, 3, at));
    expect(poseOf(initMotion(ctx({ nowMs: at })))).toEqual(poseOf(initMotion(ctx({ nowMs: at }))));
  });

  it("puts a browser that loaded earlier and one that just loaded on the same spot", () => {
    const early = simulate(initMotion(ctx()), T0, 137).state;
    const late = initMotion(ctx({ nowMs: T0 + 137_000 }));

    expect(poseOf(early).x).toBeCloseTo(poseOf(late).x, 6);
    expect(poseOf(early).z).toBeCloseTo(poseOf(late).z, 6);
  });

  it("does not depend on the frame rate", () => {
    const slow = simulate(initMotion(ctx()), T0, 200, {}, 24).state;
    const fast = simulate(initMotion(ctx()), T0, 200, {}, 144).state;

    expect(poseOf(slow).x).toBeCloseTo(poseOf(fast).x, 6);
    expect(poseOf(slow).z).toBeCloseTo(poseOf(fast).z, 6);
  });

  it("catches up after a long pause, then matches a fresh browser", () => {
    const paused = initMotion(ctx());
    const resumeAt = T0 + 5 * 60_000 + 17_000;
    const caught = simulate(paused, resumeAt, 40, {}, 30).state;
    const fresh = initMotion(ctx({ nowMs: resumeAt + 40_000 }));

    expect(poseOf(caught).x).toBeCloseTo(poseOf(fresh).x, 5);
    expect(poseOf(caught).z).toBeCloseTo(poseOf(fresh).z, 5);
  });
});
