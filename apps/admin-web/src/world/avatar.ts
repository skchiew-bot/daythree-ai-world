import * as THREE from "three";

import type { AgentState } from "./agentState";

export const STATE_COLOR: Record<AgentState, number> = {
  idle: 0x60a5fa,
  assigned: 0xa78bfa,
  working: 0xfacc15,
  thinking: 0xfacc15,
  completed: 0x4ade80,
  failed: 0xf87171,
};

export interface AvatarHandle {
  group: THREE.Group;
  statusLightMaterial: THREE.MeshStandardMaterial;
  resultRing: THREE.Mesh;
  basePosition: THREE.Vector3;
  /** Where the avatar walks to when it isn't idle — a desk (room-based avatars) or,
   * for external agents with nowhere else to go, the same spot they bob in place at. */
  workPosition: THREE.Vector3;
}

export function buildAvatar(scene: THREE.Scene, basePosition: THREE.Vector3, workPosition: THREE.Vector3): AvatarHandle {
  const group = new THREE.Group();
  const body = new THREE.Mesh(
    new THREE.CapsuleGeometry(0.28, 0.55, 6, 12),
    new THREE.MeshStandardMaterial({ color: 0xe2e8f0 }),
  );
  body.position.y = 0.62;
  group.add(body);
  const head = new THREE.Mesh(
    new THREE.SphereGeometry(0.22, 20, 16),
    new THREE.MeshStandardMaterial({ color: 0xf8fafc }),
  );
  head.position.y = 1.15;
  group.add(head);
  const statusLightMaterial = new THREE.MeshStandardMaterial({
    color: STATE_COLOR.idle,
    emissive: STATE_COLOR.idle,
    emissiveIntensity: 1.2,
  });
  const statusLight = new THREE.Mesh(new THREE.SphereGeometry(0.08, 16, 16), statusLightMaterial);
  statusLight.position.y = 1.5;
  group.add(statusLight);
  group.position.copy(basePosition);
  scene.add(group);

  const resultRing = new THREE.Mesh(
    new THREE.RingGeometry(0.4, 0.5, 32),
    new THREE.MeshBasicMaterial({ color: 0x4ade80, transparent: true, opacity: 0, side: THREE.DoubleSide }),
  );
  resultRing.rotation.x = -Math.PI / 2;
  resultRing.position.y = 0.02;
  scene.add(resultRing);

  return { group, statusLightMaterial, resultRing, basePosition, workPosition };
}

export interface AvatarAnimState {
  ringElapsed: number;
  lastState: AgentState;
}

/** Snap the avatar straight to `basePosition`/`workPosition` (no lerp) — used when an
 * avatar's *room* changes (a reassignment after suspend/reactivate), since lerping
 * across an unrelated room would look like teleporting through walls anyway. Regular
 * idle<->desk movement within the same room still lerps in updateAvatar. */
export function snapAvatar(handle: AvatarHandle, atWork: boolean) {
  const target = atWork ? handle.workPosition : handle.basePosition;
  handle.group.position.copy(target);
}

export function updateAvatar(handle: AvatarHandle, anim: AvatarAnimState, state: AgentState, t: number, dt: number) {
  const { group, statusLightMaterial, resultRing } = handle;
  const isBusy = state === "thinking" || state === "working";
  const isAtDesk = state !== "idle";
  const targetPos = isAtDesk ? handle.workPosition : handle.basePosition;

  group.position.x += (targetPos.x - group.position.x) * Math.min(1, dt * 2.5);
  group.position.z += (targetPos.z - group.position.z) * Math.min(1, dt * 2.5);

  const bobSpeed = isBusy ? 6 : 1.6;
  const bobAmount = isBusy ? 0.04 : 0.02;
  group.position.y = targetPos.y + Math.sin(t * bobSpeed) * bobAmount;
  group.rotation.y += (state === "thinking" ? 0.6 : state === "working" ? 0.15 : 0.05) * dt;

  const color = STATE_COLOR[state];
  statusLightMaterial.color.setHex(color);
  statusLightMaterial.emissive.setHex(color);
  statusLightMaterial.emissiveIntensity = state === "thinking" ? 1.2 + Math.sin(t * 10) * 0.6 : 1.2;

  if (state !== anim.lastState && (state === "completed" || state === "failed")) {
    anim.ringElapsed = 0;
    (resultRing.material as THREE.MeshBasicMaterial).color.setHex(state === "completed" ? 0x4ade80 : 0xf87171);
  }
  anim.lastState = state;

  if (state === "completed" || state === "failed") {
    anim.ringElapsed += dt;
    const progress = Math.min(1, anim.ringElapsed / 1.4);
    resultRing.position.set(group.position.x, targetPos.y + 0.02, group.position.z);
    resultRing.scale.setScalar(0.5 + progress * 3);
    (resultRing.material as THREE.MeshBasicMaterial).opacity = 0.6 * (1 - progress);
  } else {
    (resultRing.material as THREE.MeshBasicMaterial).opacity = 0;
  }
}
