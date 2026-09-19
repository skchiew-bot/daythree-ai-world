import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { createAvatarAssets, type AvatarAssets } from "./avatar";
import { disposeObject } from "./dispose";
import { createLights, fitKeyLight, type SceneLights } from "./lighting";
import { createMaterials, type MaterialSet } from "./materials";
import { createVehicleAssets, type VehicleAssets } from "./vehicles";

const MAX_PIXEL_RATIO = 2;
const FOV = 42;
/** The town overview (ADR-014): raised and pulled back so the residence, the hall and all
 * six streets fit in frame. Exported so the camera rig can return to it. */
export const OVERVIEW_POSITION = new THREE.Vector3(2, 62, 100);
export const OVERVIEW_TARGET = new THREE.Vector3(2, 0, 38);
const GROUND_SIZE = 320;
const GROUND_CENTER_Z = 40;
/** W1's paver plaza (was 40 m), trimmed to stop short of the main street. */
const PLAZA_SIZE = 30;
const PLAZA_CENTER_Z = -1;
const FOG_NEAR = 130;
const FOG_FAR = 360;
const CAMERA_FAR = 420;
const MAX_CAMERA_DISTANCE = 170;
/** Zoom-out per unit of canvas aspect ratio: the town is ~115 m wide, so a narrow canvas
 * pulls back rather than crops. */
const ZOOM_PER_ASPECT = 0.6;
const MIN_ZOOM = 0.25;

export interface SceneKit {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  lights: SceneLights;
  materials: MaterialSet;
  avatarAssets: AvatarAssets;
  vehicleAssets: VehicleAssets;
  /** Re-sizes the canvas to the container. Also called by the internal ResizeObserver. */
  resize: () => void;
  dispose: () => void;
}

function flatPlane(size: number, material: THREE.Material, x: number, y: number, z: number): THREE.Mesh {
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(size, size), material);
  plane.rotation.x = -Math.PI / 2;
  plane.position.set(x, y, z);
  plane.receiveShadow = true;
  return plane;
}

/** W1's dark paver plaza stays around the residence; a plain, lighter lawn under it
 * carries the town out to the horizon. */
function buildGround(materials: MaterialSet): THREE.Group {
  const lawn = new THREE.MeshStandardMaterial({ color: 0x8fae7f, roughness: 1 });
  const ground = new THREE.Group();
  ground.add(flatPlane(GROUND_SIZE, lawn, 0, -0.08, GROUND_CENTER_Z));
  ground.add(flatPlane(PLAZA_SIZE, materials.all.plaza, 0, -0.05, PLAZA_CENTER_Z));
  return ground;
}

function createRenderer(container: HTMLElement): THREE.WebGLRenderer {
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, MAX_PIXEL_RATIO));
  renderer.setSize(container.clientWidth, container.clientHeight, false);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  // Out of flow and CSS-sized, so the canvas can never hold its container wider than the page.
  Object.assign(renderer.domElement.style, { position: "absolute", inset: "0", width: "100%", height: "100%", display: "block" });
  container.appendChild(renderer.domElement);
  return renderer;
}

function createControls(camera: THREE.Camera, element: HTMLElement): OrbitControls {
  const controls = new OrbitControls(camera, element);
  controls.target.copy(OVERVIEW_TARGET);
  controls.enableDamping = true;
  controls.minDistance = 3;
  controls.maxDistance = MAX_CAMERA_DISTANCE;
  controls.maxPolarAngle = Math.PI / 2.05;
  return controls;
}

function releaseRenderer(renderer: THREE.WebGLRenderer): void {
  renderer.dispose();
  renderer.forceContextLoss();
  renderer.domElement.remove();
}

/** The renderer is created first: `new WebGLRenderer` throws when WebGL is unavailable,
 * and at that point nothing else exists yet to leak. If anything after it throws, the
 * renderer and its GL context are released before the error propagates. */
export function createSceneKit(container: HTMLElement, floors: number): SceneKit {
  const renderer = createRenderer(container);
  try {
    return assembleKit(container, renderer, floors);
  } catch (error) {
    releaseRenderer(renderer);
    throw error;
  }
}

function assembleKit(container: HTMLElement, renderer: THREE.WebGLRenderer, floors: number): SceneKit {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xbcd4ea);
  scene.fog = new THREE.Fog(0xbcd4ea, FOG_NEAR, FOG_FAR);

  const materials = createMaterials();
  const avatarAssets = createAvatarAssets();
  const vehicleAssets = createVehicleAssets();
  const lights = createLights(scene);
  fitKeyLight(lights.key, floors);
  scene.add(buildGround(materials));

  const camera = new THREE.PerspectiveCamera(FOV, container.clientWidth / Math.max(container.clientHeight, 1), 0.1, CAMERA_FAR);
  camera.position.copy(OVERVIEW_POSITION);
  const controls = createControls(camera, renderer.domElement);

  function resize() {
    const width = container.clientWidth;
    const height = Math.max(container.clientHeight, 1);
    camera.aspect = width / height;
    // A narrow canvas would crop the town's width, so pull back rather than crop.
    camera.zoom = Math.min(1, Math.max(MIN_ZOOM, camera.aspect * ZOOM_PER_ASPECT));
    camera.updateProjectionMatrix();
    renderer.setSize(width, height, false);
  }
  resize();
  const observer = new ResizeObserver(resize);
  observer.observe(container);

  return {
    scene,
    camera,
    renderer,
    controls,
    lights,
    materials,
    avatarAssets,
    vehicleAssets,
    resize,
    dispose: () => {
      observer.disconnect();
      controls.dispose();
      lights.key.shadow.dispose();
      disposeObject(scene);
      materials.dispose();
      avatarAssets.dispose();
      vehicleAssets.dispose();
      releaseRenderer(renderer);
    },
  };
}
