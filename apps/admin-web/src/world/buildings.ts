import * as THREE from "three";

import { GeometryBatcher } from "./batch";
import { buildingHeight, buildingSpec, FLOOR_HEIGHT_M, type BuildingSpec } from "./buildingSpec";
import type { WorldProject } from "./renderPayload";
import { buildSign, type SignMesh } from "./signage";
import { HALL_CENTER, HALL_DEPTH, HALL_WIDTH, type TownPlan, type Vec2 } from "./town";
import type { TownMaterials } from "./townMaterials";
import { addTownScenery } from "./townScenery";

/** Something a click can select: a project building (key = project id) or the hall. */
export interface BuildingPick {
  key: string;
  x: number;
  z: number;
  height: number;
}

export const HALL_KEY = "hall";

export interface BuildingsHandle {
  group: THREE.Group;
  picks: readonly BuildingPick[];
  /** Invisible hit boxes for raycasting; each carries `userData.key`. */
  pickables: readonly THREE.Object3D[];
  /** Frees this group's geometry, signs and hit boxes. Shared town materials belong to
   * the scene. */
  dispose: () => void;
}

const DOOR_W = 0.7;
const DOOR_H = 1.15;
const SIGN_Y = 1.7;
const MAX_SIGN_W = 2.7;
const SIGN_SPEC_SHARE = 0.62;
const PYRAMID_HEIGHT = 1.2;

function pyramid(width: number, height: number, depth: number): THREE.BufferGeometry {
  // radius sqrt(1/2) puts the base corners at (+/-0.5, +/-0.5) once rotated a quarter turn
  const geometry = new THREE.CylinderGeometry(0, Math.SQRT1_2, 1, 4, 1);
  geometry.rotateY(Math.PI / 4);
  geometry.scale(width, height, depth);
  return geometry;
}

function addRoof(b: GeometryBatcher, spec: BuildingSpec, cx: number, cz: number): void {
  const h = buildingHeight(spec);
  const roof = `roofP${spec.palette}`;
  const { width, depth } = spec;
  if (spec.roof === "flat") {
    b.box(roof, width + 0.2, 0.18, depth + 0.2, cx, h + 0.09, cz);
    b.box("trim", width * 0.3, 0.5, depth * 0.3, cx + width * 0.2, h + 0.43, cz - depth * 0.15);
  } else if (spec.roof === "step") {
    b.box(roof, width + 0.15, 0.2, depth + 0.15, cx, h + 0.1, cz);
    b.box(roof, width * 0.7, 0.5, depth * 0.7, cx, h + 0.45, cz);
  } else {
    b.add(roof, pyramid(width + 0.3, PYRAMID_HEIGHT, depth + 0.3), cx, h + PYRAMID_HEIGHT / 2, cz);
  }
}

function addWindows(b: GeometryBatcher, spec: BuildingSpec, cx: number, cz: number): void {
  const frontZ = cz + spec.depth / 2 + 0.02;
  for (let floor = 0; floor < spec.floors; floor++) {
    const y = floor * FLOOR_HEIGHT_M + 0.95;
    for (const side of [-1, 1]) {
      b.box("windowGlass", 0.62, 0.6, 0.05, cx + side * spec.width * 0.27, y, frontZ);
      b.box("windowGlass", 0.05, 0.6, 0.62, cx + side * (spec.width / 2 + 0.02), y, cz);
    }
  }
}

function addBuilding(b: GeometryBatcher, spec: BuildingSpec, center: Vec2): void {
  const h = buildingHeight(spec);
  b.box(`wallP${spec.palette}`, spec.width, h, spec.depth, center.x, h / 2, center.z);
  b.box("door", DOOR_W, DOOR_H, 0.06, center.x, DOOR_H / 2, center.z + spec.depth / 2 + 0.015);
  addWindows(b, spec, center.x, center.z);
  addRoof(b, spec, center.x, center.z);
}

function addHallColumns(b: GeometryBatcher, cx: number, frontZ: number): void {
  for (const dx of [-0.32, -0.11, 0.11, 0.32]) {
    b.cylinder("hallTrim", 0.12, 0.12, 2.4, cx + dx * HALL_WIDTH, 1.3, frontZ + 1.35, 10);
  }
}

function addHall(b: GeometryBatcher): void {
  const { x: cx, z: cz } = HALL_CENTER;
  const h = 3.4;
  const frontZ = cz + HALL_DEPTH / 2;
  b.box("hallWall", HALL_WIDTH, h, HALL_DEPTH, cx, h / 2, cz);
  b.box("hallRoof", HALL_WIDTH + 0.4, 0.3, HALL_DEPTH + 0.4, cx, h + 0.15, cz);
  b.box("hallStep", HALL_WIDTH * 0.7, 0.2, 1.4, cx, 0.1, frontZ + 0.7);
  b.box("hallTrim", HALL_WIDTH * 0.75, 0.25, 1.5, cx, 2.6, frontZ + 0.75);
  addHallColumns(b, cx, frontZ);
  b.box("door", 1.4, 2.0, 0.06, cx, 1.0, frontZ + 0.015);
  for (const dx of [-3.3, -2.2, 2.2, 3.3]) b.box("windowGlass", 0.7, 1.1, 0.05, cx + dx, 1.7, frontZ + 0.02);
  b.box("hallWall", 1.8, 2.2, 1.8, cx, h + 0.3 + 1.1, cz - 1);
  b.add("hallRoof", pyramid(2.2, 1.3, 2.2), cx, h + 0.3 + 2.2 + 0.65, cz - 1);
  b.sphere("lampGlow", 0.34, cx, h + 0.3 + 1.5, cz - 1 + 0.95);
}

function makePick(key: string, x: number, z: number, height: number, width: number, depth: number, material: THREE.Material): THREE.Mesh {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(width, height, depth), material);
  mesh.position.set(x, height / 2, z);
  mesh.visible = false;
  mesh.userData.key = key;
  return mesh;
}

function finish(
  scene: THREE.Scene,
  batch: GeometryBatcher,
  town: TownMaterials,
  signs: SignMesh[],
  pickMeshes: THREE.Mesh[],
  picks: BuildingPick[],
  pickMaterial: THREE.Material,
): BuildingsHandle {
  const group = batch.build(town.all, () => false);
  signs.forEach((sign) => group.add(sign.mesh));
  pickMeshes.forEach((mesh) => group.add(mesh));
  scene.add(group);
  return {
    group,
    picks,
    pickables: pickMeshes,
    dispose: () => {
      scene.remove(group);
      group.traverse((node) => (node as THREE.Mesh).geometry?.dispose());
      signs.forEach((sign) => sign.dispose());
      pickMaterial.dispose();
    },
  };
}

/** Roads, lot pads, lamps, trees and the community hall: static for the life of the scene,
 * built once. The hall's sign reads "HALL" (no free text). */
export function buildTownStatic(scene: THREE.Scene, town: TownMaterials, plan: TownPlan): BuildingsHandle {
  const batch = new GeometryBatcher();
  addTownScenery(batch, plan);
  addHall(batch);

  const { x, z } = HALL_CENTER;
  const sign = buildSign("HALL", 2.6, x, 3.0, z + HALL_DEPTH / 2 + 0.035);
  const pickMaterial = new THREE.MeshBasicMaterial({ visible: false });
  const pick = makePick(HALL_KEY, x, z, 3.4, HALL_WIDTH, HALL_DEPTH, pickMaterial);
  return finish(scene, batch, town, [sign], [pick], [{ key: HALL_KEY, x, z, height: 3.4 }], pickMaterial);
}

/** One building per project on its assigned lot. Rebuilt only when the project set (or a
 * project's lot or code) changes, never on a data poll. A project with no lot (past the 48
 * cap) gets no building. */
export function buildProjectBuildings(
  scene: THREE.Scene,
  town: TownMaterials,
  plan: TownPlan,
  projects: readonly WorldProject[],
  lotOf: ReadonlyMap<string, number>,
): BuildingsHandle {
  const batch = new GeometryBatcher();
  const signs: SignMesh[] = [];
  const pickMeshes: THREE.Mesh[] = [];
  const picks: BuildingPick[] = [];
  const pickMaterial = new THREE.MeshBasicMaterial({ visible: false });

  for (const project of projects) {
    const lotIndex = lotOf.get(project.id);
    if (lotIndex === undefined) continue;
    const { center } = plan.lots[lotIndex];
    const spec = buildingSpec(project.id, lotIndex);
    addBuilding(batch, spec, center);

    const signWidth = Math.min(spec.width * SIGN_SPEC_SHARE, MAX_SIGN_W);
    signs.push(buildSign(project.code, signWidth, center.x, SIGN_Y, center.z + spec.depth / 2 + 0.035));
    const height = buildingHeight(spec);
    pickMeshes.push(makePick(project.id, center.x, center.z, height, spec.width, spec.depth, pickMaterial));
    picks.push({ key: project.id, x: center.x, z: center.z, height });
  }
  return finish(scene, batch, town, signs, pickMeshes, picks, pickMaterial);
}
