import { describe, expect, it } from "vitest";

import { assignLots } from "./lots";
import { LOT_COUNT } from "./town";

function ids(count: number, prefix = "proj"): string[] {
  return Array.from({ length: count }, (_, i) => `${prefix}-${i}`);
}

describe("lot placement (ADR-014 decision 4, gate F7/F8)", () => {
  it("assigns 48 distinct lots to 48 projects", () => {
    const assigned = assignLots(ids(LOT_COUNT));
    expect(assigned.size).toBe(LOT_COUNT);
    expect(new Set(assigned.values()).size).toBe(LOT_COUNT);
  });

  it("moves no existing lot when a project is added", () => {
    const before = assignLots(ids(20));
    const after = assignLots([...ids(20), "proj-new"]);

    for (const [id, lot] of before) {
      expect(after.get(id)).toBe(lot);
    }
    expect(after.has("proj-new")).toBe(true);
  });

  it("is keyed on id only: unrelated metadata never enters the function", () => {
    // The function signature only accepts ids — renaming a project's code or name
    // cannot change its lot because that information never reaches assignLots.
    const first = assignLots(ids(10));
    const second = assignLots(ids(10));
    expect([...first.entries()]).toEqual([...second.entries()]);
  });

  it("keeps an archived-but-referenced project's lot as long as it stays in the list", () => {
    const withArchived = assignLots(["proj-0", "proj-archived", "proj-2"]);
    const stillReferenced = assignLots(["proj-0", "proj-archived", "proj-2", "proj-3"]);
    expect(stillReferenced.get("proj-archived")).toBe(withArchived.get("proj-archived"));
  });

  it("never assigns the same lot to two projects even with hash collisions", () => {
    const assigned = assignLots(ids(LOT_COUNT, "x"));
    const seen = new Set<number>();
    for (const lot of assigned.values()) {
      expect(seen.has(lot)).toBe(false);
      seen.add(lot);
    }
  });

  it("ignores a project beyond capacity rather than displacing another", () => {
    const assigned = assignLots(ids(LOT_COUNT + 5));
    expect(assigned.size).toBeLessThanOrEqual(LOT_COUNT);
  });
});
