import { describe, expect, it, vi } from "vitest";

import { runWorld, type WorldDeps, type WorldInputs } from "./runWorld";
import type { SceneKit } from "./sceneSetup";

const INPUTS: WorldInputs = {
  agents: [],
  agentStates: new Map(),
  floors: 5,
  externalNames: [],
  externalStates: new Map(),
};

function fakeKit(): SceneKit & { dispose: ReturnType<typeof vi.fn> } {
  return { dispose: vi.fn() } as unknown as SceneKit & { dispose: ReturnType<typeof vi.fn> };
}

describe("runWorld setup failure", () => {
  it("disposes the scene kit and rethrows when building the apartment throws", () => {
    const kit = fakeKit();
    const deps: WorldDeps = {
      createKit: () => kit,
      buildApartment: () => {
        throw new Error("geometry merge failed");
      },
    };

    expect(() => runWorld({} as HTMLElement, () => INPUTS, deps)).toThrow("geometry merge failed");
    expect(kit.dispose).toHaveBeenCalledTimes(1);
  });

  it("propagates a createKit failure (no WebGL) without trying to dispose anything", () => {
    const build = vi.fn();
    const deps: WorldDeps = {
      createKit: () => {
        throw new Error("WebGL is not available");
      },
      buildApartment: build,
    };

    expect(() => runWorld({} as HTMLElement, () => INPUTS, deps)).toThrow("WebGL is not available");
    expect(build).not.toHaveBeenCalled();
  });
});
