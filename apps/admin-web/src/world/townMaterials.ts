import * as THREE from "three";

import { disposeMaterial } from "./dispose";
import { PALETTE_COUNT } from "./buildingSpec";
import type { SceneMaterials } from "./materials";

const WALL_COLORS = [0xe8d5b7, 0xc9d6df, 0xd9c2c2, 0xcfe0c3, 0xf0d9a5, 0xb9c4e0, 0xe6b8a2, 0xd6d6d6];
const ROOF_COLORS = [0x8c4a3a, 0x3f5b73, 0x6b4f6b, 0x4a6b4a, 0x9a6b2f, 0x3c3f5c, 0x7a3b2e, 0x555b63];

function standard(color: number, roughness = 0.85): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({ color, roughness, metalness: 0 });
}

export interface TownMaterials {
  /** The scene's shared materials plus the town's own; what a GeometryBatcher resolves. */
  all: SceneMaterials;
  dispose: () => void;
}

/** Town materials, built once per scene. `base` are W1's shared materials (`windowGlass`
 * follows the clock, `lampGlow` too), reused so night looks right without new plumbing.
 * `dispose` frees only what this function created. */
export function createTownMaterials(base: SceneMaterials): TownMaterials {
  const own: SceneMaterials = {
    asphalt: standard(0x3a4049, 0.95),
    laneLine: standard(0xf2e9b0, 0.9),
    sidewalk: standard(0xb9bfc7, 0.9),
    lotPad: standard(0xc9d8bd, 0.95),
    door: standard(0x5a3d2b, 0.7),
    hallWall: standard(0xf3e5c8),
    hallRoof: standard(0x8c4a3a),
    hallTrim: standard(0xfaf6ee, 0.6),
    hallStep: standard(0xa8aeb8, 0.8),
    trunk: standard(0x6b4a2f),
  };
  for (let i = 0; i < PALETTE_COUNT; i++) {
    own[`wallP${i}`] = standard(WALL_COLORS[i]);
    own[`roofP${i}`] = standard(ROOF_COLORS[i]);
  }
  return {
    all: { ...base, ...own },
    dispose: () => Object.values(own).forEach(disposeMaterial),
  };
}
