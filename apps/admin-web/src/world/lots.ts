/** Stable lot placement (ADR-014 decision 4, gate findings F7, F8): a project's lot is a
 * pure function of `project.id` alone, probed in the order the API returns `projects[]`.
 * That array is in (created_at, id) order (guaranteed by the API since PR #28; `ProjectSummary`
 * carries no `created_at`, so the order is the only signal). Never re-sort by id or code: ids
 * are typically random UUIDs, so sorting by id would let a newly created project land ahead of
 * an older one and shuffle everyone's lot. Processing the given order and only ever appending
 * new projects at the end keeps existing lots fixed (gate finding F7).
 *
 * Known limit: a project that leaves the list (archived and no longer referenced) frees its
 * lot, and a project after it in the order may then move into an earlier free probe slot. */
import { LOT_COUNT } from "./town";
import { hashString } from "./rng";

/** Maps each project id (in the order given) to a lot index in [0, LOT_COUNT). A project
 * beyond LOT_COUNT concurrently-referenced ids (never happens under the 48-active cap,
 * but an archived-and-still-referenced project could in theory push past it) is left
 * unmapped rather than looping forever or displacing another project. */
export function assignLots(projectIds: readonly string[]): Map<string, number> {
  const assigned = new Map<string, number>();
  const taken = new Array<boolean>(LOT_COUNT).fill(false);

  for (const id of projectIds) {
    if (assigned.has(id)) continue;
    const home = hashString(id) % LOT_COUNT;
    for (let probe = 0; probe < LOT_COUNT; probe++) {
      const candidate = (home + probe) % LOT_COUNT;
      if (taken[candidate]) continue;
      taken[candidate] = true;
      assigned.set(id, candidate);
      break;
    }
  }
  return assigned;
}
