import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { createAvatarAssets, type AvatarAssets } from "./avatar";
import { disposeObject } from "./dispose";
import { createLights, fitKeyLight, type SceneLights } from "./lighting";
import { createMaterials, type MaterialSet } from "./materials";

const MAX_PIXEL_RATIO = 2;
const FOV = 42;
const CAMERA_START = new THREE.Vector3(5.5, 6, 16.5);
const CAMERA_TARGET = new THREE.Vector3(0, 4.3, 0.8);

export interface SceneKit {
  scene: THREE.Scene;
  camera: THREE.PerspectiveCamera;
  renderer: THREE.WebGLRenderer;
  controls: OrbitControls;
  lights: SceneLights;
  materials: MaterialSet;
  avatarAssets: AvatarAssets;
  /** Re-sizes the canvas to the container. Also called by the internal ResizeObserver. */
  resize: () => void;
  dispose: () => void;
}

function buildGround(materials: MaterialSet): THREE.Mesh {
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(40, 40), materials.all.plaza);
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.05;
  ground.receiveShadow = true;
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
  controls.target.copy(CAMERA_TARGET);
  controls.enableDamping = true;
  controls.minDistance = 3;
  controls.maxDistance = 30;
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
  scene.fog = new THREE.Fog(0xbcd4ea, 22, 55);

  const materials = createMaterials();
  const avatarAssets = createAvatarAssets();
  const lights = createLights(scene);
  fitKeyLight(lights.key, floors);
  scene.add(buildGround(materials));

  const camera = new THREE.PerspectiveCamera(FOV, container.clientWidth / Math.max(container.clientHeight, 1), 0.1, 120);
  camera.position.copy(CAMERA_START);
  const controls = createControls(camera, renderer.domElement);

  function resize() {
    const width = container.clientWidth;
    const height = Math.max(container.clientHeight, 1);
    camera.aspect = width / height;
    // A narrow canvas would crop the building's width, so pull back rather than crop.
    camera.zoom = Math.min(1, Math.max(0.35, camera.aspect / 0.9));
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
    resize,
    dispose: () => {
      observer.disconnect();
      controls.dispose();
      lights.key.shadow.dispose();
      disposeObject(scene);
      materials.dispose();
      avatarAssets.dispose();
      releaseRenderer(renderer);
    },
  };
}
