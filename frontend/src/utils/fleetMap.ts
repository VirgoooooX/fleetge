import { geoEqualEarth, type GeoProjection } from "d3-geo";
import type { FleetMapHost, FleetMapSnapshot } from "@/api/fleetMap";

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
 * Equal Earth keeps every longitude visible in a compact, globe-like outline.
 * Rotating its central meridian lets the map roll horizontally without hiding
 * nodes on a back side, unlike a true orthographic globe.
 */
export function createFleetProjection(
  width: number,
  height: number,
  padding = 24,
  rotation: [number, number] = [-FLEET_MAP_FOCUS[1], 0],
): GeoProjection {
  const safeWidth = Math.max(width, padding * 2 + 1);
  const safeHeight = Math.max(height, padding * 2 + 1);
  return geoEqualEarth()
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

export interface FleetLocationDraft {
  name: string;
  city: string;
  region: string;
  country: string;
  country_code: string;
  latitude: number | undefined;
  longitude: number | undefined;
}

export const fleetStatusKey = {
  online: "map.online",
  degraded: "map.issues",
  offline: "map.offline",
  unknown: "map.unknown",
} as const;

function estimateDistanceKm(lat1: number, lon1: number, lat2: number, lon2: number) {
  const radians = Math.PI / 180;
  const a = Math.sin((lat2 - lat1) * radians / 2) ** 2
    + Math.cos(lat1 * radians) * Math.cos(lat2 * radians) * Math.sin((lon2 - lon1) * radians / 2) ** 2;
  return Math.round(6371 * 2 * Math.asin(Math.sqrt(Math.min(1, a))));
}

function estimateRttMs(distanceKm: number) {
  if (distanceKm <= 5) return 1;
  if (distanceKm < 50) return 6;
  if (distanceKm < 200) return 14;
  return Math.round(15 + distanceKm * 0.016);
}

function rttTone(status: FleetMapHost["status"], ms: number | null) {
  if (status === "offline") return "offline";
  if (ms === null) return "unknown";
  if (ms < 30) return "excellent";
  if (ms < 120) return "good";
  return "fair";
}

export function buildFleetTopology(snapshot: FleetMapSnapshot | null) {
  let locatedCount = 0;
  let rttCount = 0;
  let sumRtt = 0;
  const center = snapshot?.center;
  const hasCenter = center && Number.isFinite(center.latitude) && Number.isFinite(center.longitude);
  const nodes = (snapshot?.hosts ?? []).map((host) => {
    const location = host.location;
    const hasLocation = location && Number.isFinite(location.latitude) && Number.isFinite(location.longitude);
    if (hasLocation) locatedCount++;
    const distanceKm = hasCenter && hasLocation
      ? estimateDistanceKm(center.latitude, center.longitude, location.latitude, location.longitude)
      : null;
    const rttMs = distanceKm === null ? null : estimateRttMs(distanceKm);
    if (rttMs !== null && host.status !== "offline") {
      rttCount++;
      sumRtt += rttMs;
    }
    return {
      host_id: host.host_id,
      display_name: host.display_name,
      status: host.status,
      container_count: host.container_count,
      effectiveIp: host.network_identity?.effectiveIp || "—",
      locationText: location ? [location.city || location.region, location.country].filter(Boolean).join(", ") : "",
      distanceKm,
      rttMs,
      rttTone: rttTone(host.status, rttMs),
      host,
    };
  });
  return { nodes, locatedCount, averageRttMs: rttCount ? Math.round(sumRtt / rttCount) : 0 };
}
