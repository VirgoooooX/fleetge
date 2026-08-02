import { describe, expect, it } from "vitest";
import {
  clusterProjectedNodes,
  calculateGeographicFocus,
  createFleetProjection,
  filterFleetHosts,
  projectFleetPoint,
} from "./fleetMap";
import type { FleetMapHost } from "@/stores/fleetMap";

const hosts: FleetMapHost[] = [
  { host_id: "online", display_name: "Online", enabled: true, status: "online", container_count: 1, location: { latitude: 1, longitude: 2, confirmed: true }, stacks: [] },
  { host_id: "degraded", display_name: "Degraded", enabled: true, status: "degraded", container_count: 1, location: { latitude: 3, longitude: 4, confirmed: false }, stacks: [] },
  { host_id: "legacy", display_name: "Legacy", enabled: true, status: "unknown", container_count: 0, location: null, stacks: [] },
];

describe("Fleet Map data helpers", () => {
  it("keeps unlocated legacy hosts visible", () => {
    expect(filterFleetHosts(hosts, "unlocated", false).map((host) => host.host_id)).toEqual(["legacy"]);
  });

  it("treats unknown nodes as issues", () => {
    expect(filterFleetHosts(hosts, "all", true).map((host) => host.host_id)).toEqual(["degraded", "legacy"]);
  });

  it("centres the complete world on China's central meridian", () => {
    const projection = createFleetProjection(1200, 620);
    const china = projectFleetPoint(projection, [35, 105]);
    const losAngeles = projectFleetPoint(projection, [34.05, -118.24]);

    expect(china).not.toBeNull();
    expect(losAngeles).not.toBeNull();
    expect(china![0]).toBeCloseTo(600, 3);
    expect(losAngeles![0]).toBeGreaterThan(24);
    expect(losAngeles![0]).toBeLessThan(1176);
  });

  it("clusters overlapping projected hosts while preserving distant nodes", () => {
    const clusters = clusterProjectedNodes([
      { item: "a", point: [100, 100] },
      { item: "b", point: [112, 106] },
      { item: "c", point: [300, 300] },
    ], 24);

    expect(clusters).toHaveLength(2);
    expect(clusters.find((cluster) => cluster.items.includes("a"))?.items).toEqual(["a", "b"]);
    expect(clusters.find((cluster) => cluster.items.includes("c"))?.items).toEqual(["c"]);
  });

  it("centres dateline-spanning hosts on the Pacific", () => {
    const focus = calculateGeographicFocus([[35, 170], [35, -170]]);
    expect(Math.abs(focus[1])).toBeCloseTo(180, 5);
  });

});
