import type { AgentState } from "./agentState";
import { buildApartment, type ApartmentHandle } from "./apartment";
import { CameraRig } from "./cameraRig";
import { ExternalAvatars } from "./externalAvatars";
import { applyClockTint, fitKeyLight } from "./lighting";
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
 * building (key = project id) or the hall; `focus(null)` returns to the town overview. */
export interface WorldHandle {
  focus: (key: string | null) => void;
  dispose: () => void;
}

export interface WorldHooks {
  /** Called when a click on a building changes the focus, so the page can mirror it. */
  onFocusChange?: (key: string | null) => void;
}

const DEFAULT_DEPS: WorldDeps = { createKit: createSceneKit, buildApartment };
const MAX_FRAME_SECONDS = 0.25;
const TINT_INTERVAL_SECONDS = 1;
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

  const focus = (key: string | null): void => {
    const pick = key === null ? undefined : town.pickFor(key);
    rig.focus(pick ?? null, motion.isReduced());
  };
  const detachPicking = attachPicking(kit.renderer.domElement, kit.camera, () => town.pickables, (key) => {
    focus(key);
    hooks.onFocusChange?.(key);
  });

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
    const clock: FrameClock = { t: elapsed, dt, nowMs: Date.now(), reducedMotion: motion.isReduced() };
    townAvatars.update(inputs.agents, inputs.agentStates, apartment, town.lotOf, clock);
    externalAvatars.update(inputs.externalNames, inputs.externalStates, clock);

    rig.update(dt);
    kit.controls.update();
    kit.renderer.render(scene, kit.camera);
  }
  frameId = requestAnimationFrame(frame);

  return {
    focus,
    dispose: () => {
      cancelAnimationFrame(frameId);
      motion.stop();
      detachPicking();
      rig.dispose();
      townAvatars.dispose();
      externalAvatars.dispose();
      town.dispose();
      apartment.dispose();
      kit.dispose();
    },
  };
}
