import { geoNaturalEarth1, type GeoProjection } from "d3-geo";

export type FleetMapFilter = "all" | "online" | "degraded" | "offline" | "unlocated";
export type LatLngTuple = [number, number];
export type ProjectedPoint = [number, number];

export interface ProjectedMapNode<T> {
  item: T;
  point: ProjectedPoint;
}

export interface ProjectedMapCluster<T> {
  items: T[];
  point: ProjectedPoint;
}

export const FLEET_MAP_FOCUS: LatLngTuple = [35, 105];

type FilterableHost = {
  status: "online" | "degraded" | "offline" | "unknown";
  location?: unknown;
};

export function filterFleetHosts<T extends FilterableHost>(hosts: T[], filter: FleetMapFilter, onlyIssues: boolean): T[] {
  return hosts.filter((host) => {
    if (onlyIssues && !["degraded", "offline", "unknown"].includes(host.status)) return false;
    if (filter === "unlocated") return !host.location;
    if (filter === "offline") return ["offline", "unknown"].includes(host.status);
    if (filter === "all") return true;
    return host.status === filter;
  });
}

/**
 * Natural Earth keeps the complete world visible while rotating the central
 * meridian to 105°E. This is a real China-centred projection, not a cropped
 * slippy-map viewport.
 */
export function createFleetProjection(
  width: number,
  height: number,
  padding = 24,
  rotation: [number, number] = [-FLEET_MAP_FOCUS[1], 0],
): GeoProjection {
  const safeWidth = Math.max(width, padding * 2 + 1);
  const safeHeight = Math.max(height, padding * 2 + 1);
  return geoNaturalEarth1()
    .rotate(rotation)
    .precision(0.2)
    .fitExtent(
      [[padding, padding], [safeWidth - padding, safeHeight - padding]],
      { type: "Sphere" },
    );
}

export function projectFleetPoint(projection: GeoProjection, point: LatLngTuple): [number, number] | null {
  const projected = projection([point[1], point[0]]);
  return projected ? [projected[0], projected[1]] : null;
}

/** Circular longitude mean keeps locations around ±180° centred on the Pacific. */
export function calculateGeographicFocus(points: LatLngTuple[]): LatLngTuple {
  if (!points.length) return FLEET_MAP_FOCUS;
  const latitude = points.reduce((sum, point) => sum + point[0], 0) / points.length;
  const longitudeVector = points.reduce((vector, point) => {
    const radians = point[1] * Math.PI / 180;
    vector.x += Math.cos(radians);
    vector.y += Math.sin(radians);
    return vector;
  }, { x: 0, y: 0 });
  const longitude = Math.atan2(longitudeVector.y, longitudeVector.x) * 180 / Math.PI;
  return [Math.max(-60, Math.min(60, latitude)), longitude];
}

/** Group nodes that overlap in screen space. Connected neighbours form one stable cluster. */
export function clusterProjectedNodes<T>(nodes: ProjectedMapNode<T>[], threshold: number): ProjectedMapCluster<T>[] {
  const parent = nodes.map((_, index) => index);
  const find = (index: number): number => {
    while (parent[index] !== index) {
      parent[index] = parent[parent[index]];
      index = parent[index];
    }
    return index;
  };
  const join = (left: number, right: number) => {
    const leftRoot = find(left);
    const rightRoot = find(right);
    if (leftRoot !== rightRoot) parent[rightRoot] = leftRoot;
  };

  for (let left = 0; left < nodes.length; left += 1) {
    for (let right = left + 1; right < nodes.length; right += 1) {
      const dx = nodes[left].point[0] - nodes[right].point[0];
      const dy = nodes[left].point[1] - nodes[right].point[1];
      if (Math.hypot(dx, dy) <= threshold) join(left, right);
    }
  }

  const groups = new Map<number, ProjectedMapNode<T>[]>();
  nodes.forEach((node, index) => {
    const root = find(index);
    const group = groups.get(root) || [];
    group.push(node);
    groups.set(root, group);
  });

  return Array.from(groups.values()).map((group) => ({
    items: group.map((node) => node.item),
    point: [
      group.reduce((sum, node) => sum + node.point[0], 0) / group.length,
      group.reduce((sum, node) => sum + node.point[1], 0) / group.length,
    ],
  }));
}
