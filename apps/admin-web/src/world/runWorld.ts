import type { AgentState } from "./agentState";
import { buildApartment, type ApartmentHandle } from "./apartment";
import { ExternalAvatars } from "./externalAvatars";
import { applyClockTint, fitKeyLight } from "./lighting";
import type { WorldAgent } from "./renderPayload";
import { RoomAvatars, type FrameClock } from "./roomAvatars";
import { createSceneKit } from "./sceneSetup";

/** Everything the render loop reads each frame. Only allow-listed data lives here. */
export interface WorldInputs {
  agents: readonly WorldAgent[];
  agentStates: ReadonlyMap<string, AgentState>;
  floors: number;
  externalNames: readonly string[];
  externalStates: ReadonlyMap<string, AgentState>;
}

const MAX_FRAME_SECONDS = 0.25;
const TINT_INTERVAL_SECONDS = 1;
const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/** Builds the scene inside `container`, runs it, and returns a teardown function that
 * frees every geometry, material, texture and the WebGL context. */
export function runWorld(container: HTMLElement, read: () => WorldInputs): () => void {
  const first = read();
  const kit = createSceneKit(container, first.floors);
  const { scene, lights, materials } = kit;
  let apartment: ApartmentHandle = buildApartment(scene, first.floors, materials);
  const roomAvatars = new RoomAvatars(scene, kit.avatarAssets);
  const externalAvatars = new ExternalAvatars(scene, kit.avatarAssets);
  applyClockTint(scene, lights, materials, new Date());

  const motionQuery = window.matchMedia(REDUCED_MOTION_QUERY);
  let reducedMotion = motionQuery.matches;
  const onMotionChange = (event: MediaQueryListEvent) => {
    reducedMotion = event.matches;
  };
  motionQuery.addEventListener("change", onMotionChange);

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
      apartment = buildApartment(scene, inputs.floors, materials);
      fitKeyLight(lights.key, inputs.floors);
    }
    if (sinceTint >= TINT_INTERVAL_SECONDS) {
      applyClockTint(scene, lights, materials, new Date());
      sinceTint = 0;
    }

    const clock: FrameClock = { t: elapsed, dt, nowMs: Date.now(), reducedMotion };
    roomAvatars.update(inputs.agents, inputs.agentStates, apartment, clock);
    externalAvatars.update(inputs.externalNames, inputs.externalStates, clock);

    kit.controls.update();
    kit.renderer.render(scene, kit.camera);
  }
  frameId = requestAnimationFrame(frame);

  return () => {
    cancelAnimationFrame(frameId);
    motionQuery.removeEventListener("change", onMotionChange);
    roomAvatars.dispose();
    externalAvatars.dispose();
    apartment.dispose();
    kit.dispose();
  };
}
