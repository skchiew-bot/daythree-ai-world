import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

import type { SceneMaterials } from "./materials";

interface BoxOptions {
  /** Rotation about the y axis, radians. */
  ry?: number;
  /** Repeat the material's texture every this many metres (floors, corridor). */
  uvTile?: number;
}

/** Collects the building's static parts and merges them into one mesh per material, so a
 * whole floor of furniture costs a handful of draw calls instead of hundreds. */
export class GeometryBatcher {
  private readonly buckets = new Map<string, THREE.BufferGeometry[]>();
  private readonly placer = new THREE.Object3D();

  box(material: string, w: number, h: number, d: number, x: number, y: number, z: number, options: BoxOptions = {}): void {
    const geometry = new THREE.BoxGeometry(w, h, d);
    if (options.uvTile) this.scaleUv(geometry, w / options.uvTile, d / options.uvTile);
    this.place(material, geometry, x, y, z, options.ry ?? 0);
  }

  cylinder(
    material: string,
    radiusTop: number,
    radiusBottom: number,
    height: number,
    x: number,
    y: number,
    z: number,
    segments = 12,
  ): void {
    this.place(material, new THREE.CylinderGeometry(radiusTop, radiusBottom, height, segments), x, y, z, 0);
  }

  sphere(material: string, radius: number, x: number, y: number, z: number, squashY = 1): void {
    const geometry = new THREE.SphereGeometry(radius, 14, 10);
    geometry.scale(1, squashY, 1);
    this.place(material, geometry, x, y, z, 0);
  }

  /** Merges each material's parts into one mesh. `castsShadow` decides per material. */
  build(materials: SceneMaterials, castsShadow: (material: string) => boolean): THREE.Group {
    const group = new THREE.Group();
    for (const [key, parts] of this.buckets) {
      const material = materials[key];
      if (!material) throw new Error(`Unknown material "${key}"`);
      const merged = mergeGeometries(parts, false);
      parts.forEach((part) => part.dispose());
      const mesh = new THREE.Mesh(merged, material);
      mesh.castShadow = castsShadow(key);
      mesh.receiveShadow = true;
      group.add(mesh);
    }
    this.buckets.clear();
    return group;
  }

  private scaleUv(geometry: THREE.BufferGeometry, su: number, sv: number): void {
    const uv = geometry.getAttribute("uv");
    for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * su, uv.getY(i) * sv);
    uv.needsUpdate = true;
  }

  private place(material: string, geometry: THREE.BufferGeometry, x: number, y: number, z: number, ry: number): void {
    this.placer.position.set(x, y, z);
    this.placer.rotation.set(0, ry, 0);
    this.placer.updateMatrix();
    geometry.applyMatrix4(this.placer.matrix);
    const bucket = this.buckets.get(material) ?? [];
    bucket.push(geometry);
    this.buckets.set(material, bucket);
  }
}
