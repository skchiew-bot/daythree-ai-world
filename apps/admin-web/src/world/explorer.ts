/** Owns everything W3 adds on top of the W1/W2 scene: the operator avatar, walk-mode
 * input and camera, follow-mode camera, proximity detection and the twin pick proxies.
 * `runWorld` creates one Explorer per running world and calls its methods only from the
 * mode that owns the camera that frame (deliverable 2). */
import * as THREE from "three";

import type { AgentState } from "./agentState";
import { buildAvatar, createAnimState, updateAvatar, type AvatarAnimState, type AvatarAssets, type AvatarHandle } from "./avatar";
import { isInsideAny, OPERATOR_RADIUS_M, resolvePosition } from "./collision";
import { attachExplorePointer } from "./explorePointer";
import {
  buildingDoors,
  footprints as computeFootprints,
  projectSignature,
  townBounds,
  type Bounds,
  type Door,
  type Footprint,
} from "./footprints";
import { attachExploreKeyboard, type ExploreKeyboard } from "./keyHeld";
import { nearestDoor } from "./proximity";
import type { WorldAgent, WorldProject } from "./renderPayload";
import { walkCameraPose } from "./springArm";
import { RESIDENCE_ENTRANCE } from "./town";
import type { TownAvatars } from "./townAvatars";
import { isMoving, stepWalk as computeWalkStep, type WalkKeys, type WalkState } from "./walkMotion";

export type ExploreMode = "fly" | "walk" | "follow";

export interface ProximityInfo {
  code: string;
  status: string;
  twins: readonly { display_name: string; activity: string }[];
}

export interface FollowInfo {
  agentId: string;
  display_name: string;
  activity: string;
  place: string;
}

export interface ExplorerCallbacks {
  onEscape: () => void;
  /** A click in walk or follow mode picked a twin (deliverable 6). */
  onPickAgent: (agentId: string) => void;
}

const OPERATOR_SEED = "operator";
const OPERATOR_STATE: AgentState = "idle";
const FOLLOW_OFFSET_BACK_M = 4;
const FOLLOW_OFFSET_UP_M = 2.2;
/** Radians of heading turned per pixel of horizontal drag. */
const TURN_SENSITIVITY = 0.006;
const PICK_HIT_SIZE_M = 0.7;
const PICK_HIT_HEIGHT_M = 1.6;

function agentPickKey(mesh: THREE.Object3D): string | null {
  const key = mesh.userData.key;
  return typeof key === "string" && key.startsWith("agent:") ? key.slice("agent:".length) : null;
}

export class Explorer {
  readonly operator: AvatarHandle;
  private readonly anim: AvatarAnimState;
  private readonly keyboard: ExploreKeyboard;
  private readonly detachPointer: () => void;
  private readonly bounds: Bounds = townBounds();
  private readonly pickGeometry = new THREE.BoxGeometry(PICK_HIT_SIZE_M, PICK_HIT_HEIGHT_M, PICK_HIT_SIZE_M);
  private readonly pickMaterial = new THREE.MeshBasicMaterial({ visible: false });
  private readonly pickMeshes = new Map<string, THREE.Mesh>();
  private readonly scratchPose = { x: 0, z: 0, heading: 0 };

  private walk: WalkState = { x: RESIDENCE_ENTRANCE.x, z: RESIDENCE_ENTRANCE.z + 2, heading: Math.PI };
  private headingDelta = 0;
  private elapsed = 0;
  private footCache: { signature: string; list: Footprint[]; doors: Door[] } = { signature: "", list: [], doors: [] };
  followAgentId: string | null = null;

  constructor(
    private readonly scene: THREE.Scene,
    avatarAssets: AvatarAssets,
    private readonly camera: THREE.PerspectiveCamera,
    exploreElement: HTMLElement,
    callbacks: ExplorerCallbacks,
  ) {
    this.operator = buildAvatar(scene, avatarAssets, OPERATOR_SEED, 0);
    this.anim = createAnimState(OPERATOR_SEED);
    this.keyboard = attachExploreKeyboard(exploreElement, { onEscape: callbacks.onEscape });
    this.detachPointer = attachExplorePointer(exploreElement, {
      onTurn: (deltaX) => {
        this.headingDelta += deltaX * TURN_SENSITIVITY;
      },
      onClick: (clientX, clientY) => this.handleClick(clientX, clientY, exploreElement, callbacks.onPickAgent),
    });
    this.applyOperatorPose(0);
  }

  get walkState(): Readonly<WalkState> {
    return this.walk;
  }

  /** Building footprints for the currently loaded project set (deliverable 3, 10):
   * recomputed only when `syncFootprints` sees the signature change. */
  get footprints(): readonly Footprint[] {
    return this.footCache.list;
  }

  /** Recomputes footprints and doors only when the project set changed. Returns true
   * when it recomputed (deliverable 10). */
  syncFootprints(projects: readonly WorldProject[], lotOf: ReadonlyMap<string, number>): boolean {
    const signature = projectSignature(projects);
    if (signature === this.footCache.signature) return false;
    this.footCache = { signature, list: computeFootprints(projects, lotOf), doors: buildingDoors(projects, lotOf) };
    return true;
  }

  /** Pushes the operator outside any footprint it now stands inside (W3-F6: a freed lot a
   * shifted project just filled). Call after every `syncFootprints`, in every mode, so a
   * later switch into walk mode never starts the operator trapped. */
  settleOperator(): void {
    if (!isInsideAny(this.walk.x, this.walk.z, this.footCache.list)) return;
    const pushed = resolvePosition(this.walk.x, this.walk.z, this.footCache.list);
    this.walk = { x: pushed.x, z: pushed.z, heading: this.walk.heading };
    this.applyOperatorPose(0);
  }

  /** Moves the operator directly (minimap teleport, deliverable 7). The caller is
   * expected to have already resolved collision against `this.footprints`; this only
   * clamps to the town bounds and re-poses the avatar. */
  teleportTo(x: number, z: number): void {
    const bounded = clampInBounds(x, z, this.bounds);
    this.walk = { x: bounded.x, z: bounded.z, heading: this.walk.heading };
    this.applyOperatorPose(0);
  }

  /** Clears the accumulated drag turn — called when walk mode is (re-)entered so a drag
   * made while in another mode never causes a jump on the next walk frame. */
  resetTurn(): void {
    this.headingDelta = 0;
  }

  /** Zeroes every held direction (deliverable 8: cleared "on ... mode switch"). Esc is
   * handled inside the same keydown listener that sets `held.forward` etc. and never
   * blurs the element, so nothing in `keyHeld.ts` clears it on its own — the caller
   * (`runWorld`'s `setMode`) calls this on every transition, so a key still physically
   * down when the mode changes can never silently resume movement on the next walk
   * entry; it takes a fresh keydown. */
  clearHeldKeys(): void {
    this.keyboard.clear();
  }

  /** Advances the operator by one walk-mode frame: movement, collision, the avatar's own
   * animation, and the spring-arm camera. This is the only place W3 writes `camera`
   * outside of `stepFollow` (deliverable 2: fly owns the camera in every other mode). */
  stepWalk(dt: number, camera: THREE.PerspectiveCamera): void {
    const keys: WalkKeys = {
      forward: this.keyboard.held.forward,
      backward: this.keyboard.held.backward,
      left: this.keyboard.held.left,
      right: this.keyboard.held.right,
      running: this.keyboard.held.running,
    };
    const moved = computeWalkStep(this.walk, keys, this.headingDelta, dt);
    this.headingDelta = 0;
    const bounded = clampInBounds(moved.x, moved.z, this.bounds);
    const settled = resolvePosition(bounded.x, bounded.z, this.footCache.list, OPERATOR_RADIUS_M);
    this.walk = { x: settled.x, z: settled.z, heading: moved.heading };

    this.applyOperatorPose(dt, isMoving(keys), keys.running);

    const pose = walkCameraPose(this.walk, this.footCache.list);
    camera.position.set(pose.x, pose.y, pose.z);
    camera.lookAt(pose.lookX, pose.lookY, pose.lookZ);
  }

  /** Within-range building door, for the proximity card (deliverable 4). Only meaningful
   * in walk mode. */
  updateProximity(agents: readonly WorldAgent[], projects: readonly WorldProject[]): ProximityInfo | null {
    const hit = nearestDoor(this.walk.x, this.walk.z, this.footCache.doors);
    if (!hit) return null;
    const project = projects.find((p) => p.id === hit.key);
    if (!project) return null;
    const twins = agents
      .filter((a) => a.project_id === project.id)
      .map((a) => ({ display_name: a.display_name, activity: a.activity }));
    return { code: project.code, status: project.status, twins };
  }

  /** Rides the camera behind a followed twin (deliverable 5). Returns null, and clears
   * the follow target, once the twin is gone or has arrived at the residence (W3-F3):
   * `poseOf` already reports false in both cases, so this never reads a disposed handle. */
  stepFollow(camera: THREE.PerspectiveCamera, townAvatars: TownAvatars, agents: readonly WorldAgent[], projects: readonly WorldProject[]): FollowInfo | null {
    if (!this.followAgentId) return null;
    const found = townAvatars.poseOf(this.followAgentId, this.scratchPose);
    if (!found) {
      this.followAgentId = null;
      return null;
    }
    const agent = agents.find((a) => a.agent_id === this.followAgentId);
    if (!agent) {
      this.followAgentId = null;
      return null;
    }

    const dirX = -Math.sin(this.scratchPose.heading);
    const dirZ = -Math.cos(this.scratchPose.heading);
    camera.position.set(
      this.scratchPose.x + dirX * FOLLOW_OFFSET_BACK_M,
      FOLLOW_OFFSET_UP_M,
      this.scratchPose.z + dirZ * FOLLOW_OFFSET_BACK_M,
    );
    camera.lookAt(this.scratchPose.x, 1.2, this.scratchPose.z);

    return {
      agentId: agent.agent_id,
      display_name: agent.display_name,
      activity: agent.activity,
      place: placeLabel(agent, projects),
    };
  }

  /** Keeps one invisible pick proxy per twin currently out in town, positioned at its
   * live pose. Cheap: only added/removed on membership change, repositioned (not
   * reallocated) every other frame. */
  syncAgentPickables(townAvatars: TownAvatars): void {
    for (const [id, mesh] of this.pickMeshes) {
      if (townAvatars.hasAway(id)) continue;
      this.scene.remove(mesh);
      this.pickMeshes.delete(id);
    }
    for (const id of townAvatars.awayIds) {
      let mesh = this.pickMeshes.get(id);
      if (!mesh) {
        mesh = new THREE.Mesh(this.pickGeometry, this.pickMaterial);
        mesh.visible = false;
        mesh.userData.key = `agent:${id}`;
        this.scene.add(mesh);
        this.pickMeshes.set(id, mesh);
      }
      townAvatars.poseOf(id, this.scratchPose);
      mesh.position.set(this.scratchPose.x, PICK_HIT_HEIGHT_M / 2, this.scratchPose.z);
    }
  }

  dispose(): void {
    this.keyboard.dispose();
    this.detachPointer();
    for (const mesh of this.pickMeshes.values()) this.scene.remove(mesh);
    this.pickMeshes.clear();
    this.pickGeometry.dispose();
    this.pickMaterial.dispose();
    this.operator.dispose();
  }

  private handleClick(clientX: number, clientY: number, element: HTMLElement, onPickAgent: (agentId: string) => void): void {
    const rect = element.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(ndc, this.camera);
    const hit = raycaster.intersectObjects([...this.pickMeshes.values()], false)[0];
    const agentId = hit ? agentPickKey(hit.object) : null;
    if (agentId) onPickAgent(agentId);
  }

  private applyOperatorPose(dt: number, walking = false, running = false): void {
    this.elapsed += dt;
    const speed = running ? 2.4 : 1.1;
    updateAvatar(
      this.operator,
      this.anim,
      OPERATOR_STATE,
      { x: this.walk.x, z: this.walk.z, heading: this.walk.heading, speed: walking ? speed : 0, walking, atDesk: false, phase: "room" },
      this.elapsed,
      dt,
      false,
    );
  }
}

function clampInBounds(x: number, z: number, bounds: Bounds): { x: number; z: number } {
  return {
    x: Math.min(Math.max(x, bounds.minX), bounds.maxX),
    z: Math.min(Math.max(z, bounds.minZ), bounds.maxZ),
  };
}

function placeLabel(agent: WorldAgent, projects: readonly WorldProject[]): string {
  if (agent.project_id) {
    const project = projects.find((p) => p.id === agent.project_id);
    if (project) return project.code;
  }
  return "Community hall";
}
