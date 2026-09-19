import { describe, expect, it } from "vitest";

import { buildingDoors, footprints, projectSignature, townBounds } from "./footprints";
import { assignLots } from "./lots";
import { toWorldProject } from "./renderPayload";

function project(id: string, code = id.toUpperCase()) {
  return toWorldProject({ id, code, name: "Client name", status: "active" });
}

describe("footprints (ADR-014 W3 deliverable 3)", () => {
  it("always includes the residence and the hall", () => {
    const list = footprints([], new Map());
    const keys = list.map((f) => f.key);
    expect(keys).toContain("residence");
    expect(keys).toContain("hall");
    expect(list).toHaveLength(2);
  });

  it("adds one rectangle per project with a lot, and none for a project past capacity", () => {
    const projects = [project("p-1"), project("p-2")];
    const lotOf = assignLots(projects.map((p) => p.id));
    const list = footprints(projects, lotOf);
    expect(list.map((f) => f.key)).toEqual(expect.arrayContaining(["p-1", "p-2"]));

    const noLot = footprints([project("p-3")], new Map());
    expect(noLot.map((f) => f.key)).not.toContain("p-3");
  });

  it("gives every project rectangle a positive width and depth", () => {
    const projects = [project("p-1"), project("p-2"), project("p-3")];
    const lotOf = assignLots(projects.map((p) => p.id));
    for (const fp of footprints(projects, lotOf)) {
      expect(fp.maxX).toBeGreaterThan(fp.minX);
      expect(fp.maxZ).toBeGreaterThan(fp.minZ);
    }
  });

  it("keeps a door at each project building's front, none for the hall or residence", () => {
    const projects = [project("p-1"), project("p-2")];
    const lotOf = assignLots(projects.map((p) => p.id));
    const doors = buildingDoors(projects, lotOf);
    expect(doors.map((d) => d.key).sort()).toEqual(["p-1", "p-2"]);
  });

  it("computes bounds that contain every lot and the hall", () => {
    const bounds = townBounds();
    expect(bounds.maxX).toBeGreaterThan(bounds.minX);
    expect(bounds.maxZ).toBeGreaterThan(bounds.minZ);
  });

  it("has a signature that changes only when the id:code set changes", () => {
    const a = [project("p-1"), project("p-2")];
    const b = [project("p-1"), project("p-2")];
    const c = [project("p-1"), project("p-3")];
    expect(projectSignature(a)).toBe(projectSignature(b));
    expect(projectSignature(a)).not.toBe(projectSignature(c));
  });
});
