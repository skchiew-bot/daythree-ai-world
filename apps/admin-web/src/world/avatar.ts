import * as THREE from "three";

import type { Pose } from "./agentMotion";
import type { AgentState } from "./agentState";
import { WALK_SPEED } from "./idleSchedule";
import { hashString } from "./rng";

export const STATE_COLOR: Record<AgentState, number> = {
  idle: 0x60a5fa,
  assigned: 0xa78bfa,
  working: 0xfacc15,
  thinking: 0xfacc15,
  completed: 0x4ade80,
  failed: 0xf87171,
};

const SHIRT_COLORS = [0x2a9d8f, 0xe76f51, 0x5468d4, 0xe9c46a, 0xd6688e, 0x4f9d5b, 0x3aa6d8, 0x8b5cf6];
const RIG_SCALE = 0.92;
const STRIDE_RATE = 5.7;
const SWING = 0.65;
const SEATED_LEGS = -1.45;
const BLEND_RATE = 10;
const RING_SECONDS = 1.4;

export interface AvatarAssets {
  torso: THREE.BufferGeometry;
  head: THREE.BufferGeometry;
  visor: THREE.BufferGeometry;
  arm: THREE.BufferGeometry;
  leg: THREE.BufferGeometry;
  antenna: THREE.BufferGeometry;
  light: THREE.BufferGeometry;
  ring: THREE.BufferGeometry;
  skin: THREE.MeshStandardMaterial;
  visorMaterial: THREE.MeshStandardMaterial;
  shirts: THREE.MeshStandardMaterial[];
  dispose: () => void;
}

/** Geometry and materials every avatar shares, built once per scene. */
export function createAvatarAssets(): AvatarAssets {
  const arm = new THREE.CapsuleGeometry(0.045, 0.2, 3, 8).translate(0, -0.145, 0);
  const leg = new THREE.CapsuleGeometry(0.06, 0.26, 3, 8).translate(0, -0.19, 0);
  const geometries = {
    torso: new THREE.CapsuleGeometry(0.15, 0.22, 4, 12),
    head: new THREE.SphereGeometry(0.17, 20, 16),
    visor: new THREE.BoxGeometry(0.24, 0.075, 0.08),
    antenna: new THREE.CylinderGeometry(0.008, 0.008, 0.12, 6),
    light: new THREE.SphereGeometry(0.055, 14, 12),
    ring: new THREE.RingGeometry(0.4, 0.5, 32),
    arm,
    leg,
  };
  const skin = new THREE.MeshStandardMaterial({ color: 0xf1f5f9, roughness: 0.55 });
  const visorMaterial = new THREE.MeshStandardMaterial({
    color: 0x0f172a, roughness: 0.15, metalness: 0.4, emissive: 0x38bdf8, emissiveIntensity: 0.35,
  });
  const shirts = SHIRT_COLORS.map((color) => new THREE.MeshStandardMaterial({ color, roughness: 0.75 }));

  return {
    ...geometries,
    skin,
    visorMaterial,
    shirts,
    dispose: () => {
      Object.values(geometries).forEach((g) => g.dispose());
      [skin, visorMaterial, ...shirts].forEach((m) => m.dispose());
    },
  };
}

interface Limbs {
  head: THREE.Mesh;
  armL: THREE.Mesh;
  armR: THREE.Mesh;
  legL: THREE.Mesh;
  legR: THREE.Mesh;
}

export interface AvatarHandle {
  group: THREE.Group;
  rig: THREE.Group;
  limbs: Limbs;
  statusLightMaterial: THREE.MeshStandardMaterial;
  resultRing: THREE.Mesh;
  floorY: number;
  /** Frees the materials this avatar owns and takes it out of the scene. */
  dispose: () => void;
}

export interface AvatarAnimState {
  ringElapsed: number;
  lastState: AgentState;
  walkPhase: number;
  walkBlend: number;
  seatBlend: number;
  seed: number;
}

export function createAnimState(colorSeed: string): AvatarAnimState {
  const seed = (hashString(colorSeed) % 1000) / 1000;
  return { ringElapsed: 0, lastState: "idle", walkPhase: seed * 6, walkBlend: 0, seatBlend: 0, seed: seed * 6.28 };
}

function mesh(geometry: THREE.BufferGeometry, material: THREE.Material, x: number, y: number, z: number): THREE.Mesh {
  const part = new THREE.Mesh(geometry, material);
  part.position.set(x, y, z);
  part.castShadow = true;
  return part;
}

function buildRig(assets: AvatarAssets, shirt: THREE.Material, statusLight: THREE.Material): { rig: THREE.Group; limbs: Limbs } {
  const rig = new THREE.Group();
  rig.scale.setScalar(RIG_SCALE);
  const head = mesh(assets.head, assets.skin, 0, 1.1, 0);
  head.add(mesh(assets.visor, assets.visorMaterial, 0, 0.01, 0.13));
  head.add(mesh(assets.antenna, assets.skin, 0, 0.2, 0));
  const bulb = mesh(assets.light, statusLight, 0, 0.28, 0);
  bulb.castShadow = false;
  head.add(bulb);

  const limbs: Limbs = {
    head,
    armL: mesh(assets.arm, shirt, -0.205, 0.86, 0),
    armR: mesh(assets.arm, shirt, 0.205, 0.86, 0),
    legL: mesh(assets.leg, assets.skin, -0.08, 0.42, 0),
    legR: mesh(assets.leg, assets.skin, 0.08, 0.42, 0),
  };
  rig.add(mesh(assets.torso, shirt, 0, 0.66, 0), head, limbs.armL, limbs.armR, limbs.legL, limbs.legR);
  return { rig, limbs };
}

export function buildAvatar(scene: THREE.Scene, assets: AvatarAssets, colorSeed: string, floorY: number): AvatarHandle {
  const shirt = assets.shirts[hashString(colorSeed) % assets.shirts.length];
  const statusLightMaterial = new THREE.MeshStandardMaterial({
    color: STATE_COLOR.idle,
    emissive: STATE_COLOR.idle,
    emissiveIntensity: 1.2,
  });
  const { rig, limbs } = buildRig(assets, shirt, statusLightMaterial);
  const group = new THREE.Group();
  group.add(rig);
  scene.add(group);

  const ringMaterial = new THREE.MeshBasicMaterial({ color: 0x4ade80, transparent: true, opacity: 0, side: THREE.DoubleSide });
  const resultRing = new THREE.Mesh(assets.ring, ringMaterial);
  resultRing.rotation.x = -Math.PI / 2;
  scene.add(resultRing);

  return {
    group,
    rig,
    limbs,
    statusLightMaterial,
    resultRing,
    floorY,
    dispose: () => {
      scene.remove(group);
      scene.remove(resultRing);
      statusLightMaterial.dispose();
      ringMaterial.dispose();
    },
  };
}

function ease(current: number, target: number, dt: number, instant: boolean): number {
  return instant ? target : current + (target - current) * Math.min(1, dt * BLEND_RATE);
}

function isBusy(state: AgentState): boolean {
  return state === "working" || state === "thinking";
}

function poseLimbs(handle: AvatarHandle, anim: AvatarAnimState, state: AgentState, t: number): void {
  const { limbs } = handle;
  const swing = Math.sin(anim.walkPhase) * SWING * anim.walkBlend;
  const seat = anim.seatBlend;
  const busy = isBusy(state);
  const typing = busy ? Math.sin(t * 14 + anim.seed) * 0.07 : 0;
  const reach = Math.max(seat, busy ? 1 - anim.walkBlend : 0);

  limbs.legL.rotation.x = swing * (1 - seat) + SEATED_LEGS * seat;
  limbs.legR.rotation.x = -swing * (1 - seat) + SEATED_LEGS * seat;
  limbs.armL.rotation.x = -swing * 0.8 * (1 - reach) - 0.95 * reach + typing * reach;
  limbs.armR.rotation.x = swing * 0.8 * (1 - reach) - 0.95 * reach - typing * reach;
  limbs.head.rotation.z = state === "thinking" ? Math.sin(t * 2.2) * 0.12 : 0;
}

function updateStatus(handle: AvatarHandle, anim: AvatarAnimState, state: AgentState, t: number, dt: number, still: boolean): void {
  const color = STATE_COLOR[state];
  const { statusLightMaterial, resultRing } = handle;
  statusLightMaterial.color.setHex(color);
  statusLightMaterial.emissive.setHex(color);
  statusLightMaterial.emissiveIntensity = state === "thinking" && !still ? 1.2 + Math.sin(t * 10) * 0.6 : 1.2;

  const ringMaterial = resultRing.material as THREE.MeshBasicMaterial;
  if (state !== anim.lastState && (state === "completed" || state === "failed")) {
    anim.ringElapsed = 0;
    ringMaterial.color.setHex(state === "completed" ? 0x4ade80 : 0xf87171);
  }
  anim.lastState = state;

  const showRing = state === "completed" || state === "failed";
  if (!showRing) {
    ringMaterial.opacity = 0;
    return;
  }
  anim.ringElapsed += dt;
  const progress = still ? 0 : Math.min(1, anim.ringElapsed / RING_SECONDS);
  resultRing.position.set(handle.group.position.x, handle.floorY + 0.02, handle.group.position.z);
  resultRing.scale.setScalar(still ? 1.5 : 0.5 + progress * 3);
  ringMaterial.opacity = still ? 0.35 : 0.6 * (1 - progress);
}

/** Drives one avatar from its pose. Walking speed sets the stride rate, so the gait is
 * frame-rate independent. With reduced motion there is no walk cycle, bob, sway or ring
 * pulse: the pose is applied as given. */
export function updateAvatar(
  handle: AvatarHandle,
  anim: AvatarAnimState,
  state: AgentState,
  pose: Pose,
  t: number,
  dt: number,
  reducedMotion: boolean,
): void {
  const walking = pose.walking && !reducedMotion;
  anim.walkBlend = ease(anim.walkBlend, walking ? 1 : 0, dt, reducedMotion);
  anim.seatBlend = ease(anim.seatBlend, pose.atDesk && !pose.walking ? 1 : 0, dt, reducedMotion);
  anim.walkPhase += dt * STRIDE_RATE * (pose.speed / WALK_SPEED);

  const still = reducedMotion;
  const bounce = Math.abs(Math.sin(anim.walkPhase)) * 0.035 * anim.walkBlend;
  const breathe = still ? 0 : Math.sin(t * 1.6 + anim.seed) * 0.012 * (1 - anim.walkBlend);
  const sway = still || state !== "idle" ? 0 : Math.sin(t * 0.5 + anim.seed) * 0.35 * (1 - anim.walkBlend);

  handle.group.position.set(pose.x, handle.floorY, pose.z);
  handle.group.rotation.y = pose.heading + sway;
  const busyBob = still || !isBusy(state) ? 0 : Math.sin(t * 6) * 0.025 * (1 - anim.walkBlend);
  handle.rig.position.y = bounce + breathe + busyBob - 0.04 * anim.seatBlend;

  poseLimbs(handle, anim, state, t);
  updateStatus(handle, anim, state, t, dt, still);
}
