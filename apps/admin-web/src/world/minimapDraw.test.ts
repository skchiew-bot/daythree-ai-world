import { describe, expect, it, vi } from "vitest";

import type { Footprint } from "./footprints";
import { drawDynamicLayer, drawStaticLayer, type DrawCtx } from "./minimapDraw";
import type { RoadGraph } from "./town";

function fakeCtx(): DrawCtx {
  return {
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
    stroke: vi.fn(),
    fill: vi.fn(),
    arc: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    translate: vi.fn(),
    rotate: vi.fn(),
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 0,
  };
}

const BOUNDS = { minX: -10, maxX: 10, minZ: -10, maxZ: 10 };

describe("drawStaticLayer (ADR-014 W3 deliverable 7)", () => {
  it("draws each undirected road edge once and one rectangle per building", () => {
    const roads: RoadGraph = {
      nodes: new Map([
        ["a", { x: 0, z: 0 }],
        ["b", { x: 5, z: 0 }],
      ]),
      edges: new Map([
        ["a", [{ to: "b", dist: 5 }]],
        ["b", [{ to: "a", dist: 5 }]],
      ]),
    };
    const buildings: Footprint[] = [{ key: "p-1", minX: -1, maxX: 1, minZ: -1, maxZ: 1 }];
    const ctx = fakeCtx();

    drawStaticLayer(ctx, 100, BOUNDS, roads, buildings);

    expect(ctx.stroke).toHaveBeenCalledTimes(1);
    expect(ctx.fillRect).toHaveBeenCalledTimes(2); // background + one building
  });

  it("draws nothing that could be text: only rects, lines and arcs", () => {
    const roads: RoadGraph = { nodes: new Map(), edges: new Map() };
    const ctx = fakeCtx();
    drawStaticLayer(ctx, 100, BOUNDS, roads, []);
    expect(ctx.fillRect).toHaveBeenCalledTimes(1); // background only
  });
});

describe("drawDynamicLayer", () => {
  it("draws one arc per twin and one operator arrow", () => {
    const ctx = fakeCtx();
    drawDynamicLayer(ctx, 100, BOUNDS, { x: 0, z: 0, heading: 0 }, [{ x: 1, z: 1 }, { x: 2, z: 2 }]);
    expect(ctx.arc).toHaveBeenCalledTimes(2);
    expect(ctx.save).toHaveBeenCalledTimes(1);
    expect(ctx.restore).toHaveBeenCalledTimes(1);
  });
});
