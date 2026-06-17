/** Minimal StackSummary subset used for sorting — avoids circular imports. */
interface SortableStack {
  name: string;
  status: string;
}

/** Statuses that should sort to the bottom. */
const STOPPED_LIKE = new Set(["stopped", "inactive", "exited"]);

/**
 * Lower priority = higher on the page.
 * Priority 0: running, active, partially running, partial, unknown
 * Priority 1: stopped, inactive, exited
 */
function statusPriority(status: string): number {
  const normalized = status.trim().toLowerCase();
  return STOPPED_LIKE.has(normalized) ? 1 : 0;
}

/**
 * Sort stacks: running/active/partial first, stopped/inactive/exited last.
 * Within each group, alphabetical by name (localeCompare for case-insensitive).
 * Non-mutating — always returns a new array.
 */
export function sortStacks<T extends SortableStack>(stacks: T[]): T[] {
  return [...stacks].sort((a, b) => {
    const priDiff = statusPriority(a.status) - statusPriority(b.status);
    if (priDiff !== 0) return priDiff;
    return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
  });
}
