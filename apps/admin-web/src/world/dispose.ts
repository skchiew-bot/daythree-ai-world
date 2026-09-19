import * as THREE from "three";

/** Frees a material and every texture it references. */
export function disposeMaterial(material: THREE.Material): void {
  for (const value of Object.values(material)) {
    if (value instanceof THREE.Texture) value.dispose();
  }
  material.dispose();
}

type Renderable = THREE.Object3D & { geometry?: THREE.BufferGeometry; material?: THREE.Material | THREE.Material[] };

/** Frees the GPU resources of everything under `root`. Disposing a resource that is
 * shared, or disposing twice, is harmless: three.js re-uploads on the next use. */
export function disposeObject(root: THREE.Object3D): void {
  root.traverse((node) => {
    const item = node as Renderable;
    item.geometry?.dispose();
    if (Array.isArray(item.material)) item.material.forEach(disposeMaterial);
    else if (item.material) disposeMaterial(item.material);
  });
}
