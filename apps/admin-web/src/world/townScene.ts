import type * as THREE from "three";

import {
  buildProjectBuildings,
  buildTownStatic,
  type BuildingPick,
  type BuildingsHandle,
} from "./buildings";
import { assignLots } from "./lots";
import type { WorldProject } from "./renderPayload";
import { buildTownPlan, type TownPlan } from "./town";
import { createTownMaterials, type TownMaterials } from "./townMaterials";
import type { SceneMaterials } from "./materials";

export const RESIDENCE_KEY = "residence";
/** Camera focus for the residence (the sidebar can select it; it has no click target). */
const RESIDENCE_PICK: BuildingPick = { key: RESIDENCE_KEY, x: 0, z: 1, height: 8 };

/** Owns the town's static geometry (roads, lots, hall) and the project buildings. The
 * static part is built once; the project buildings are rebuilt only when the set of
 * (id, code) pairs changes, never on a data poll that changed nothing (ADR-014 W2). */
export class TownScene {
  readonly plan: TownPlan = buildTownPlan();
  private readonly town: TownMaterials;
  private readonly statics: BuildingsHandle;
  private buildings: BuildingsHandle | null = null;
  private lastProjects: readonly WorldProject[] | null = null;
  private signature = "";
  private lots: ReadonlyMap<string, number> = new Map();

  constructor(
    private readonly scene: THREE.Scene,
    base: SceneMaterials,
  ) {
    this.town = createTownMaterials(base);
    this.statics = buildTownStatic(scene, this.town, this.plan);
  }

  /** Stable lot per project id (see lots.ts). Empty until the first `sync`. */
  get lotOf(): ReadonlyMap<string, number> {
    return this.lots;
  }

  /** Number of project buildings currently standing. */
  get buildingCount(): number {
    return this.buildings?.picks.length ?? 0;
  }

  get pickables(): readonly THREE.Object3D[] {
    return [...this.statics.pickables, ...(this.buildings?.pickables ?? [])];
  }

  pickFor(key: string): BuildingPick | undefined {
    if (key === RESIDENCE_KEY) return RESIDENCE_PICK;
    return [...this.statics.picks, ...(this.buildings?.picks ?? [])].find((pick) => pick.key === key);
  }

  sync(projects: readonly WorldProject[]): void {
    if (projects === this.lastProjects) return;
    this.lastProjects = projects;

    const signature = projects.map((p) => `${p.id}:${p.code}`).join("|");
    if (signature === this.signature && this.buildings) return;
    this.signature = signature;

    this.buildings?.dispose();
    this.lots = assignLots(projects.map((p) => p.id));
    this.buildings = buildProjectBuildings(this.scene, this.town, this.plan, projects, this.lots);
  }

  dispose(): void {
    this.buildings?.dispose();
    this.buildings = null;
    this.statics.dispose();
    this.town.dispose();
  }
}
