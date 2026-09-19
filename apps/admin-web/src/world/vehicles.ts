import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

import { hashString } from "./rng";

export type RideKind = "bicycle" | "motorbike";

const FRAME_COLORS = [0xe76f51, 0x2a9d8f, 0x5468d4, 0xe9c46a, 0xd6688e, 0x4f9d5b];

interface KindAssets {
  frame: THREE.BufferGeometry;
  wheel: THREE.BufferGeometry;
  wheelRadius: number;
  wheelBase: number;
  /** How far above the ground the rider's hips sit. */
  seatHeight: number;
}

export interface VehicleAssets {
  bicycle: KindAssets;
  motorbike: KindAssets;
  frames: THREE.MeshStandardMaterial[];
  tire: THREE.MeshStandardMaterial;
  dispose: () => void;
}

function box(w: number, h: number, d: number, x: number, y: number, z: number): THREE.BufferGeometry {
  return new THREE.BoxGeometry(w, h, d).translate(x, y, z);
}

function wheelGeometry(radius: number, tube: number): THREE.BufferGeometry {
  return new THREE.TorusGeometry(radius, tube, 6, 16).rotateY(Math.PI / 2);
}

function merge(parts: THREE.BufferGeometry[]): THREE.BufferGeometry {
  const merged = mergeGeometries(parts, false);
  parts.forEach((part) => part.dispose());
  return merged;
}

function bicycleAssets(): KindAssets {
  const radius = 0.24;
  const frame = merge([
    box(0.04, 0.04, 0.7, 0, radius + 0.2, 0),
    box(0.04, 0.3, 0.04, 0, radius + 0.35, -0.22),
    box(0.1, 0.03, 0.2, 0, radius + 0.52, -0.22),
    box(0.04, 0.34, 0.04, 0, radius + 0.36, 0.36),
    box(0.42, 0.03, 0.03, 0, radius + 0.54, 0.36),
  ]);
  return { frame, wheel: wheelGeometry(radius, 0.028), wheelRadius: radius, wheelBase: 0.78, seatHeight: radius + 0.52 };
}

function motorbikeAssets(): KindAssets {
  const radius = 0.29;
  const frame = merge([
    box(0.26, 0.3, 0.55, 0, radius + 0.12, 0.02),
    box(0.22, 0.2, 0.34, 0, radius + 0.42, 0.14),
    box(0.2, 0.08, 0.5, 0, radius + 0.36, -0.22),
    box(0.06, 0.4, 0.06, 0, radius + 0.15, 0.5),
    box(0.5, 0.04, 0.04, 0, radius + 0.42, 0.52),
    box(0.16, 0.16, 0.12, 0, radius + 0.32, 0.6),
    box(0.06, 0.06, 0.4, 0.16, radius - 0.02, -0.3),
  ]);
  return { frame, wheel: wheelGeometry(radius, 0.06), wheelRadius: radius, wheelBase: 1.1, seatHeight: radius + 0.36 };
}

/** Geometry and materials every vehicle shares, built once per scene. */
export function createVehicleAssets(): VehicleAssets {
  const bicycle = bicycleAssets();
  const motorbike = motorbikeAssets();
  const frames = FRAME_COLORS.map((color) => new THREE.MeshStandardMaterial({ color, roughness: 0.5, metalness: 0.3 }));
  const tire = new THREE.MeshStandardMaterial({ color: 0x1f2328, roughness: 0.9 });
  return {
    bicycle,
    motorbike,
    frames,
    tire,
    dispose: () => {
      [bicycle, motorbike].forEach((kind) => {
        kind.frame.dispose();
        kind.wheel.dispose();
      });
      [...frames, tire].forEach((material) => material.dispose());
    },
  };
}

export interface VehicleHandle {
  kind: RideKind;
  group: THREE.Group;
  wheels: THREE.Mesh[];
  wheelRadius: number;
  seatHeight: number;
  /** Takes the vehicle out of the scene; shared geometry and materials stay with the assets. */
  dispose: () => void;
}

export function buildVehicle(scene: THREE.Scene, assets: VehicleAssets, kind: RideKind, colorSeed: string): VehicleHandle {
  const shared = assets[kind];
  const frameMaterial = assets.frames[hashString(colorSeed) % assets.frames.length];
  const group = new THREE.Group();
  const frame = new THREE.Mesh(shared.frame, frameMaterial);
  frame.castShadow = true;
  group.add(frame);

  const wheels = [-1, 1].map((side) => {
    const wheel = new THREE.Mesh(shared.wheel, assets.tire);
    wheel.position.set(0, shared.wheelRadius, (side * shared.wheelBase) / 2);
    wheel.castShadow = true;
    group.add(wheel);
    return wheel;
  });
  scene.add(group);
  return {
    kind,
    group,
    wheels,
    wheelRadius: shared.wheelRadius,
    seatHeight: shared.seatHeight,
    dispose: () => scene.remove(group),
  };
}

/** Places the vehicle and spins its wheels by `advanceMeters` of travel, so the spin rate
 * follows real speed and is frame-rate independent. */
export function updateVehicle(handle: VehicleHandle, x: number, z: number, heading: number, advanceMeters: number): void {
  handle.group.position.set(x, 0, z);
  handle.group.rotation.y = heading;
  const spin = advanceMeters / handle.wheelRadius;
  handle.wheels.forEach((wheel) => {
    wheel.rotation.x += spin;
  });
}
