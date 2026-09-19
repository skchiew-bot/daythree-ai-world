import * as THREE from "three";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { createAvatarAssets, type AvatarAssets } from "./avatar";
import { ExternalAvatars } from "./externalAvatars";
import type { FrameClock } from "./roomAvatars";

const CLOCK: FrameClock = { t: 0, dt: 1 / 60, nowMs: 0, reducedMotion: false };
/** Each avatar adds its body group and its result ring to the scene. */
const CHILDREN_PER_AVATAR = 2;

describe("ExternalAvatars name change detection", () => {
  let scene: THREE.Scene;
  let assets: AvatarAssets;
  let avatars: ExternalAvatars;

  beforeEach(() => {
    scene = new THREE.Scene();
    assets = createAvatarAssets();
    avatars = new ExternalAvatars(scene, assets);
  });

  afterEach(() => {
    avatars.dispose();
    assets.dispose();
  });

  it("does not confuse ['a|b'] with ['a', 'b']", () => {
    avatars.update(["a|b"], new Map(), CLOCK);
    expect(scene.children).toHaveLength(1 * CHILDREN_PER_AVATAR);

    avatars.update(["a", "b"], new Map(), CLOCK);
    expect(scene.children).toHaveLength(2 * CHILDREN_PER_AVATAR);
  });

  it("removes avatars whose name is gone and keeps the others", () => {
    avatars.update(["x", "y"], new Map(), CLOCK);
    avatars.update(["y"], new Map(), CLOCK);

    expect(scene.children).toHaveLength(1 * CHILDREN_PER_AVATAR);
  });

  it("does not rebuild when the same names arrive again in a new array", () => {
    avatars.update(["x", "y"], new Map(), CLOCK);
    const before = [...scene.children];

    avatars.update(["x", "y"], new Map(), CLOCK);

    expect(scene.children).toEqual(before);
  });
});
