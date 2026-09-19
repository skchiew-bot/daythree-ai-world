import * as THREE from "three";

import { disposeMaterial } from "./dispose";
import { paverTexture, plasterTexture, tileTexture, woodTexture } from "./textures";

/** Every room picks one of these colour schemes; walls, blanket and rug follow it. */
export const ACCENT_COUNT = 4;
const WALL_TINTS = [0xdcefee, 0xf7e1d7, 0xdde3f5, 0xf6ecc9];
const BLANKET_TINTS = [0x2a9d8f, 0xe76f51, 0x5468d4, 0xe9c46a];
const RUG_TINTS = [0x9ad1c9, 0xf4a992, 0x9aa8ea, 0xf0d98d];

export type SceneMaterials = Record<string, THREE.MeshStandardMaterial>;

export interface MaterialSet {
  all: SceneMaterials;
  /** Materials whose emissive strength follows the clock. */
  lamp: THREE.MeshStandardMaterial;
  screen: THREE.MeshStandardMaterial;
  window: THREE.MeshStandardMaterial;
  dispose: () => void;
}

interface Options {
  roughness?: number;
  metalness?: number;
  map?: THREE.Texture;
  emissive?: number;
  emissiveIntensity?: number;
}

function standard(color: number, options: Options = {}): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0, ...options });
}

function accentMaterials(all: SceneMaterials, plaster: THREE.Texture): void {
  for (let i = 0; i < ACCENT_COUNT; i++) {
    all[`wall${i}`] = standard(WALL_TINTS[i], { map: plaster, roughness: 0.95 });
    all[`blanket${i}`] = standard(BLANKET_TINTS[i], { roughness: 0.9 });
    all[`rug${i}`] = standard(RUG_TINTS[i], { roughness: 1 });
  }
}

function furnitureMaterials(all: SceneMaterials, wood: THREE.Texture): void {
  all.bedFrame = standard(0x8a5a36, { map: wood, roughness: 0.65 });
  all.deskWood = standard(0xd7b48a, { map: wood, roughness: 0.55 });
  all.mattress = standard(0xf1f5f9, { roughness: 0.95 });
  all.pillow = standard(0xffffff, { roughness: 1 });
  all.chairFabric = standard(0x475569, { roughness: 0.9 });
  all.bench = standard(0x5b6b8c, { roughness: 0.9 });
  all.metal = standard(0x94a3b8, { roughness: 0.35, metalness: 0.7 });
  all.monitorBody = standard(0x1e293b, { roughness: 0.4, metalness: 0.2 });
  all.foliage = standard(0x3f9d5a, { roughness: 0.85 });
  all.foliage2 = standard(0x2c7a4b, { roughness: 0.85 });
  all.pot = standard(0xd97757, { roughness: 0.7 });
  all.bookA = standard(0xb4443c);
  all.bookB = standard(0x3b6fb6);
  all.bookC = standard(0xe0b341);
  all.artCanvas = standard(0xf59e0b, { roughness: 0.6 });
}

export function createMaterials(): MaterialSet {
  const wood = woodTexture();
  const plaster = plasterTexture();
  const tile = tileTexture();
  const paver = paverTexture();
  paver.repeat.set(20, 20);
  const textures = [wood, plaster, tile, paver];

  const all: SceneMaterials = {
    floorWood: standard(0xffffff, { map: wood, roughness: 0.6 }),
    corridorTile: standard(0xffffff, { map: tile, roughness: 0.45 }),
    plaza: standard(0xffffff, { map: paver, roughness: 0.9 }),
    divider: standard(0xe9edf2, { roughness: 0.9 }),
    trim: standard(0x334155, { roughness: 0.5 }),
    railing: standard(0x2b3341, { roughness: 0.4, metalness: 0.6 }),
    lobbyRug: standard(0x8fa3c7, { roughness: 1 }),
  };
  accentMaterials(all, plaster);
  furnitureMaterials(all, wood);

  const lamp = standard(0xffe2a8, { emissive: 0xffd27a, emissiveIntensity: 1 });
  const screen = standard(0x0f172a, { emissive: 0x38bdf8, emissiveIntensity: 1 });
  const window = standard(0xbfe0ff, { emissive: 0xbfe0ff, emissiveIntensity: 0.9, roughness: 0.2 });
  all.lampGlow = lamp;
  all.screen = screen;
  all.windowGlass = window;

  return {
    all,
    lamp,
    screen,
    window,
    dispose: () => {
      Object.values(all).forEach(disposeMaterial);
      textures.forEach((t) => t.dispose());
    },
  };
}
