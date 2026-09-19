import * as THREE from "three";
import { afterEach, describe, expect, it, vi } from "vitest";

import { buildProjectBuildings, buildTownStatic } from "./buildings";
import { disposeMaterial, disposeObject } from "./dispose";
import { assignLots } from "./lots";
import type { SceneMaterials } from "./materials";
import { toWorldProject } from "./renderPayload";
import { buildTownPlan } from "./town";
import { createTownMaterials } from "./townMaterials";
import { createVehicleAssets } from "./vehicles";

function stubCanvas(): void {
  vi.stubGlobal("document", {
    createElement: () => ({ width: 0, height: 0, getContext: () => null }),
  });
}

/** The scene-owned materials the town borrows (materials.ts owns their disposal). */
function baseMaterials(): SceneMaterials {
  const make = () => new THREE.MeshStandardMaterial();
  return { windowGlass: make(), trim: make(), metal: make(), lampGlow: make(), foliage: make(), foliage2: make() };
}

/** Counts distinct geometries under `root` and how many of them have been disposed
 * (disposing one twice is harmless and counts once). */
function track(root: THREE.Object3D): { disposed: () => number; total: number } {
  const seen = new Set<THREE.BufferGeometry>();
  const freed = new Set<THREE.BufferGeometry>();
  root.traverse((node) => {
    const geometry = (node as THREE.Mesh).geometry;
    if (!geometry) return;
    seen.add(geometry);
    geometry.addEventListener("dispose", () => freed.add(geometry));
  });
  return { disposed: () => freed.size, total: seen.size };
}

afterEach(() => vi.unstubAllGlobals());

describe("disposeObject", () => {
  it("frees a material's textures along with the material", () => {
    const texture = new THREE.Texture();
    const material = new THREE.MeshStandardMaterial({ map: texture });
    const onTexture = vi.fn();
    const onMaterial = vi.fn();
    texture.addEventListener("dispose", onTexture);
    material.addEventListener("dispose", onMaterial);

    disposeMaterial(material);

    expect(onTexture).toHaveBeenCalledTimes(1);
    expect(onMaterial).toHaveBeenCalledTimes(1);
  });

  it("frees every geometry under a root", () => {
    const root = new THREE.Group();
    root.add(new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial()));
    root.add(new THREE.Mesh(new THREE.SphereGeometry(), new THREE.MeshBasicMaterial()));
    const tracked = track(root);

    disposeObject(root);

    expect(tracked.disposed()).toBe(tracked.total);
  });
});

describe("town disposal (ADR-014 W2)", () => {
  it("frees every geometry of the static town and the project buildings, and leaves the scene empty", () => {
    stubCanvas();
    const scene = new THREE.Scene();
    const town = createTownMaterials(baseMaterials());
    const plan = buildTownPlan();
    const projects = ["p-1", "p-2", "p-3"].map((id) => toWorldProject({ id, code: id.toUpperCase(), name: "Client", status: "active" }));

    const statics = buildTownStatic(scene, town, plan);
    const buildings = buildProjectBuildings(scene, town, plan, projects, assignLots(projects.map((p) => p.id)));
    const staticTrack = track(statics.group);
    const buildingTrack = track(buildings.group);
    expect(buildings.picks).toHaveLength(3);

    buildings.dispose();
    statics.dispose();

    expect(buildingTrack.disposed()).toBe(buildingTrack.total);
    expect(staticTrack.disposed()).toBe(staticTrack.total);
    expect(scene.children).toHaveLength(0);
  });

  it("leaves no project building for a project with no lot", () => {
    stubCanvas();
    const scene = new THREE.Scene();
    const town = createTownMaterials(baseMaterials());
    const project = toWorldProject({ id: "p-x", code: "X", name: "n", status: "active" });

    const buildings = buildProjectBuildings(scene, town, buildTownPlan(), [project], new Map());

    expect(buildings.picks).toHaveLength(0);
    buildings.dispose();
  });
});

describe("vehicle assets", () => {
  it("dispose frees the shared geometry", () => {
    const assets = createVehicleAssets();
    const onFrame = vi.fn();
    assets.bicycle.frame.addEventListener("dispose", onFrame);

    assets.dispose();

    expect(onFrame).toHaveBeenCalledTimes(1);
  });
});
