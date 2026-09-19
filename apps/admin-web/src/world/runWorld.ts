import type { AgentState } from "./agentState";
import { buildApartment, type ApartmentHandle } from "./apartment";
import { CameraRig } from "./cameraRig";
import { OPERATOR_RADIUS_M, resolvePosition } from "./collision";
import { Explorer, type ExploreMode, type FollowInfo, type ProximityInfo } from "./explorer";
import { ExternalAvatars } from "./externalAvatars";
import { townBounds, type Footprint } from "./footprints";
import { applyClockTint, fitKeyLight } from "./lighting";
import { drawDynamicLayer, drawStaticLayer } from "./minimapDraw";
import { minimapSummary, nearestStreetLabel, worldToCanvas } from "./minimapMath";
import { attachPicking } from "./pickController";
import type { WorldAgent, WorldProject } from "./renderPayload";
import type { FrameClock } from "./roomAvatars";
import { createSceneKit, type SceneKit } from "./sceneSetup";
import { TownAvatars } from "./townAvatars";
import { TownScene } from "./townScene";

/** Everything the render loop reads each frame. Only allow-listed data lives here. */
export interface WorldInputs {
  agents: readonly WorldAgent[];
  agentStates: ReadonlyMap<string, AgentState>;
  floors: number;
  externalNames: readonly string[];
  externalStates: ReadonlyMap<string, AgentState>;
  projects: readonly WorldProject[];
}

/** The parts of setup that can fail; injectable so the failure path can be tested. */
export interface WorldDeps {
  createKit: typeof createSceneKit;
  buildApartment: typeof buildApartment;
}

/** What the page can do with a running world. `focus(key)` moves the camera to a project
 * building (key = project id) or the hall; `focus(null)` returns to the town overview.
 * The W3 additions are no-ops when `hooks.exploreElement` was not supplied. */
export interface WorldHandle {
  focus: (key: string | null) => void;
  dispose: () => void;
  setMode: (mode: ExploreMode) => void;
  followAgent: (agentId: string) => void;
  /** Minimap click (deliverable 7): moves the operator in walk mode, focuses a building
   * under the point in fly mode, and does nothing in follow mode. */
  teleport: (x: number, z: number) => void;
}

export interface WorldHooks {
  /** Called when a click on a building changes the focus, so the page can mirror it. */
  onFocusChange?: (key: string | null) => void;
  onModeChange?: (mode: ExploreMode) => void;
  onProximityChange?: (info: ProximityInfo | null) => void;
  onFollowChange?: (info: FollowInfo | null) => void;
  onMinimapText?: (text: string) => void;
  /** Canvas-space dots for the minimap hover tooltip (D21): display_name and activity
   * only, never a project name. */
  onMinimapDots?: (dots: readonly { x: number; y: number; display_name: string; activity: string }[]) => void;
  /** The explore overlay element (deliverable 1): required for walk/follow to be
   * reachable at all. Without it the world behaves exactly as W2 did. */
  exploreElement?: HTMLElement;
  /** A small square canvas for the minimap (deliverable 7); optional like the above. */
  minimapCanvas?: HTMLCanvasElement;
}

const DEFAULT_DEPS: WorldDeps = { createKit: createSceneKit, buildApartment };
const MAX_FRAME_SECONDS = 0.25;
const TINT_INTERVAL_SECONDS = 1;
const MINIMAP_INTERVAL_SECONDS = 0.1; // C6: dynamic dots redraw at 10 Hz or less
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function trackReducedMotion(): { isReduced: () => boolean; stop: () => void } {
  const query = window.matchMedia(REDUCED_MOTION_QUERY);
  let reduced = query.matches;
  const onChange = (event: MediaQueryListEvent) => {
    reduced = event.matches;
  };
  query.addEventListener("change", onChange);
  return { isReduced: () => reduced, stop: () => query.removeEventListener("change", onChange) };
}

/** The building or hall footprint (if any) whose rectangle contains (x, z) — used for a
 * fly-mode minimap click (deliverable 7). Exact-hit only, no nearest-neighbour fallback. */
function footprintAt(x: number, z: number, footprints: readonly Footprint[]): string | null {
  for (const fp of footprints) {
    if (x >= fp.minX && x <= fp.maxX && z >= fp.minZ && z <= fp.maxZ) return fp.key;
  }
  return null;
}

/** Builds the scene inside `container`, runs it, and returns a handle whose `dispose` frees
 * every geometry, material, texture and the WebGL context. If setup throws after the
 * renderer exists, the renderer is released before the error propagates. */
export function runWorld(
  container: HTMLElement,
  read: () => WorldInputs,
  deps: WorldDeps = DEFAULT_DEPS,
  hooks: WorldHooks = {},
): WorldHandle {
  const kit = deps.createKit(container, read().floors);
  try {
    return startLoop(kit, read, deps, hooks);
  } catch (error) {
    kit.dispose();
    throw error;
  }
}

function startLoop(kit: SceneKit, read: () => WorldInputs, deps: WorldDeps, hooks: WorldHooks): WorldHandle {
  const { scene, lights, materials } = kit;
  let apartment: ApartmentHandle = deps.buildApartment(scene, read().floors, materials);
  const town = new TownScene(scene, materials.all);
  const townAvatars = new TownAvatars(scene, kit.avatarAssets, kit.vehicleAssets, town.plan);
  const externalAvatars = new ExternalAvatars(scene, kit.avatarAssets);
  const rig = new CameraRig(kit.camera, kit.controls);
  applyClockTint(scene, lights, materials, new Date());
  const motion = trackReducedMotion();
  const bounds = townBounds();

  let mode: ExploreMode = "fly";
  let explorer: Explorer | null = null;
  if (hooks.exploreElement) {
    explorer = new Explorer(scene, kit.avatarAssets, kit.camera, hooks.exploreElement, {
      onEscape: () => setMode("fly"),
      onPickAgent: (agentId) => {
        if (explorer) explorer.followAgentId = agentId;
        if (mode !== "follow") setMode("follow");
      },
    });
  }

  function setMode(next: ExploreMode): void {
    if (next === mode) return;
    if (next !== "fly") {
      rig.cancelMove();
      kit.controls.enabled = false;
    } else {
      const at = explorer?.walkState;
      kit.controls.target.set(at?.x ?? kit.controls.target.x, 1, at?.z ?? kit.controls.target.z);
      kit.controls.enabled = true;
      if (explorer) explorer.followAgentId = null;
      lastProximityKey = null;
      hooks.onProximityChange?.(null);
      lastFollowKey = null;
      hooks.onFollowChange?.(null);
    }
    if (next === "walk") explorer?.resetTurn();
    mode = next;
    hooks.onModeChange?.(next);
  }

  const focus = (key: string | null): void => {
    const pick = key === null ? undefined : town.pickFor(key);
    rig.focus(pick ?? null, motion.isReduced());
  };
  const detachPicking = attachPicking(kit.renderer.domElement, kit.camera, () => town.pickables, (key) => {
    if (mode !== "fly") return; // W3-F4: building picks apply only in fly mode
    focus(key);
    hooks.onFocusChange?.(key);
  });

  let lastProximityKey: string | null = null;
  let lastFollowKey: string | null = null;
  let staticMinimap: HTMLCanvasElement | null = null;
  let staticMinimapSignature = "";
  let sinceMinimap = 0;

  function reportProximity(info: ProximityInfo | null): void {
    const key = info ? `${info.code}|${info.status}|${info.twins.length}` : null;
    if (key === lastProximityKey) return;
    lastProximityKey = key;
    hooks.onProximityChange?.(info);
  }

  function reportFollow(info: FollowInfo | null): void {
    const key = info ? `${info.agentId}|${info.activity}|${info.place}` : null;
    if (key === lastFollowKey) return;
    lastFollowKey = info ? key : null;
    hooks.onFollowChange?.(info);
  }

  function drawMinimap(inputs: WorldInputs): void {
    const canvas = hooks.minimapCanvas;
    if (!canvas || !explorer) return;
    const size = canvas.width;
    const signature = inputs.projects.map((p) => `${p.id}:${p.code}`).join("|");
    if (signature !== staticMinimapSignature || !staticMinimap) {
      staticMinimapSignature = signature;
      staticMinimap = document.createElement("canvas");
      staticMinimap.width = size;
      staticMinimap.height = size;
      const staticCtx = staticMinimap.getContext("2d");
      if (staticCtx) drawStaticLayer(staticCtx, size, bounds, town.plan.roads, explorer.footprints);
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, size, size);
    if (staticMinimap) ctx.drawImage(staticMinimap, 0, 0);

    const twins: { x: number; z: number }[] = [];
    const dots: { x: number; y: number; display_name: string; activity: string }[] = [];
    const scratch = { x: 0, z: 0, heading: 0 };
    const agentById = new Map(inputs.agents.map((a) => [a.agent_id, a]));
    for (const id of townAvatars.awayIds) {
      if (!townAvatars.poseOf(id, scratch)) continue;
      twins.push({ x: scratch.x, z: scratch.z });
      const agent = agentById.get(id);
      if (agent) {
        const canvasPoint = worldToCanvas(scratch.x, scratch.z, bounds, size);
        dots.push({ x: canvasPoint.x, y: canvasPoint.y, display_name: agent.display_name, activity: agent.activity });
      }
    }
    drawDynamicLayer(ctx, size, bounds, explorer.walkState, twins);
    hooks.onMinimapDots?.(dots);
    hooks.onMinimapText?.(
      minimapSummary({
        buildingCodes: inputs.projects.map((p) => p.code),
        twinCount: twins.length,
        street: nearestStreetLabel(explorer.walkState.z),
      }),
    );
  }

  let frameId = 0;
  let last = performance.now();
  let elapsed = 0;
  let sinceTint = 0;

  function frame(now: number) {
    frameId = requestAnimationFrame(frame);
    const dt = Math.min(Math.max((now - last) / 1000, 0), MAX_FRAME_SECONDS);
    last = now;
    elapsed += dt;
    sinceTint += dt;
    sinceMinimap += dt;

    const inputs = read();
    if (inputs.floors !== apartment.floors) {
      apartment.dispose();
      apartment = deps.buildApartment(scene, inputs.floors, materials);
      fitKeyLight(lights.key, inputs.floors);
    }
    if (sinceTint >= TINT_INTERVAL_SECONDS) {
      applyClockTint(scene, lights, materials, new Date());
      sinceTint = 0;
    }

    town.sync(inputs.projects);
    if (explorer) {
      explorer.syncFootprints(inputs.projects, town.lotOf);
      explorer.settleOperator();
    }
    const clock: FrameClock = { t: elapsed, dt, nowMs: Date.now(), reducedMotion: motion.isReduced() };
    townAvatars.update(inputs.agents, inputs.agentStates, apartment, town.lotOf, clock);
    externalAvatars.update(inputs.externalNames, inputs.externalStates, clock);

    if (mode === "fly") {
      rig.update(dt);
      kit.controls.update();
    } else if (mode === "walk" && explorer) {
      explorer.stepWalk(dt, kit.camera);
      reportProximity(explorer.updateProximity(inputs.agents, inputs.projects));
    } else if (mode === "follow" && explorer) {
      const info = explorer.stepFollow(kit.camera, townAvatars, inputs.agents, inputs.projects);
      reportFollow(info);
      if (!info) setMode("walk");
    }
    if (explorer && mode !== "fly") explorer.syncAgentPickables(townAvatars);

    if (sinceMinimap >= MINIMAP_INTERVAL_SECONDS) {
      sinceMinimap = 0;
      drawMinimap(inputs);
    }

    kit.renderer.render(scene, kit.camera);
  }
  frameId = requestAnimationFrame(frame);

  return {
    focus,
    setMode,
    followAgent: (agentId: string) => {
      if (!explorer) return;
      explorer.followAgentId = agentId;
      setMode("follow");
    },
    teleport: (x: number, z: number) => {
      if (!explorer) return;
      if (mode === "fly") {
        const key = footprintAt(x, z, explorer.footprints);
        if (key) {
          focus(key);
          hooks.onFocusChange?.(key);
        }
        return;
      }
      if (mode === "walk") {
        const settled = resolvePosition(x, z, explorer.footprints, OPERATOR_RADIUS_M);
        explorer.teleportTo(settled.x, settled.z);
      }
    },
    dispose: () => {
      cancelAnimationFrame(frameId);
      motion.stop();
      detachPicking();
      explorer?.dispose();
      rig.dispose();
      townAvatars.dispose();
      externalAvatars.dispose();
      town.dispose();
      apartment.dispose();
      kit.dispose();
    },
  };
}
