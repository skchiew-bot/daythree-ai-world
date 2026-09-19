import * as THREE from "three";

import { localHourFraction, tintAt, type Rgb, type SceneTint } from "./dayNight";
import { BUILDING_WIDTH, FLOOR_HEIGHT } from "./layout";
import type { MaterialSet } from "./materials";

/** Shadow map resolution for the one shadow-casting light. */
const SHADOW_MAP_SIZE = 2048;

export interface SceneLights {
  hemi: THREE.HemisphereLight;
  key: THREE.DirectionalLight;
}

/** A hemisphere fill plus one key light. Only the key light casts shadows. */
export function createLights(scene: THREE.Scene): SceneLights {
  const hemi = new THREE.HemisphereLight(0xdbeafe, 0x998877, 1);
  const key = new THREE.DirectionalLight(0xfff4e0, 2.5);
  key.castShadow = true;
  key.shadow.mapSize.set(SHADOW_MAP_SIZE, SHADOW_MAP_SIZE);
  key.shadow.bias = -0.0004;
  key.shadow.normalBias = 0.04;
  key.shadow.radius = 3;
  scene.add(hemi, key, key.target);
  return { hemi, key };
}

/** Points the key light at the middle of the building and sizes its shadow frustum to
 * fit, so the shadow map is not wasted on empty ground. */
export function fitKeyLight(key: THREE.DirectionalLight, floors: number): void {
  const height = floors * FLOOR_HEIGHT;
  const target = new THREE.Vector3(0, height / 2, 0.6);
  key.target.position.copy(target);
  key.position.copy(target).add(new THREE.Vector3(6.5, 8.5 + height * 0.35, 9));

  const reach = Math.hypot(BUILDING_WIDTH / 2 + 1.5, height / 2 + 1.5, 3.5);
  const camera = key.shadow.camera;
  camera.left = -reach;
  camera.right = reach;
  camera.top = reach;
  camera.bottom = -reach;
  camera.near = 1;
  camera.far = reach * 2 + 20;
  camera.updateProjectionMatrix();
  key.target.updateMatrixWorld();
}

function setRgb(color: THREE.Color, rgb: Rgb): void {
  color.setRGB(rgb[0], rgb[1], rgb[2], THREE.SRGBColorSpace);
}

export function applyTint(scene: THREE.Scene, lights: SceneLights, materials: MaterialSet, tint: SceneTint): void {
  setRgb(scene.background as THREE.Color, tint.sky);
  if (scene.fog) setRgb(scene.fog.color, tint.sky);

  setRgb(lights.key.color, tint.keyColor);
  lights.key.intensity = tint.keyIntensity;
  setRgb(lights.hemi.color, tint.hemiSky);
  setRgb(lights.hemi.groundColor, tint.hemiGround);
  lights.hemi.intensity = tint.hemiIntensity;

  materials.lamp.emissiveIntensity = tint.lampGlow;
  materials.screen.emissiveIntensity = 0.5 + tint.lampGlow * 0.5;
  setRgb(materials.window.color, tint.windowColor);
  setRgb(materials.window.emissive, tint.windowColor);
}

/** Re-tints the scene from the local clock. Every input is continuous, so calling this
 * once a second is enough for a change nobody can see happening. */
export function applyClockTint(scene: THREE.Scene, lights: SceneLights, materials: MaterialSet, now: Date): void {
  applyTint(scene, lights, materials, tintAt(localHourFraction(now)));
}
