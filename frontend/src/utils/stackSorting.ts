/** Minimal StackSummary subset used for sorting — avoids circular imports. */
interface SortableStack {
  name: string;
  status: string;
  management_status?: string;
}

/** Statuses that should sort to the bottom. */
const STOPPED_LIKE = new Set(["stopped", "inactive", "exited"]);

/**
 * Lower priority = higher on the page.
 * Priority 0: Managed running/active/partial/unknown
 * Priority 1: Unmanaged (非受控)
 * Priority 2: Managed exited (已退出)
 * Priority 3: Managed stopped/inactive (未启动)
 */
function getStackPriority(stack: SortableStack): number {
  const isUnmanaged = stack.management_status === "unmanaged";
  if (isUnmanaged) {
    return 1;
  }

  const normalizedStatus = stack.status.trim().toLowerCase();
  if (normalizedStatus === "exited") {
    return 2;
  }
  if (normalizedStatus === "stopped" || normalizedStatus === "inactive") {
    return 3;
  }

  return 0;
}

/**
 * Sort stacks: managed active first, managed stopped second, unmanaged active third, unmanaged stopped last.
 * Within each group, alphabetical by name (localeCompare for case-insensitive).
 * Non-mutating — always returns a new array.
 */
export function sortStacks<T extends SortableStack>(stacks: T[]): T[] {
  return [...stacks].sort((a, b) => {
    const priDiff = getStackPriority(a) - getStackPriority(b);
    if (priDiff !== 0) return priDiff;
    return a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
  });
}
