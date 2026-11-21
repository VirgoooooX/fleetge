import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getFleetSnapshot, updateFleetHostLocation, type FleetMapSnapshot } from "@/api/fleetMap";
import { useFleetMapStore } from "./fleetMap";

vi.mock("@/i18n", () => ({ t: (key: string) => key }));
vi.mock("@/api/fleetMap", () => ({
  getFleetSnapshot: vi.fn(),
  getFleetCenterSettings: vi.fn(),
  searchFleetLocations: vi.fn(),
  suggestFleetCenterLocation: vi.fn(),
  updateFleetHostLocation: vi.fn(),
}));

function snapshot(): FleetMapSnapshot {
  return {
    center: { name: "Fleetge", latitude: 0, longitude: 0, confirmed: false },
    hosts: [{ host_id: "host", display_name: "Host", enabled: true, status: "online", container_count: 0, stacks: [] }],
    counts: { total: 1, online: 1, degraded: 0, offline: 0, unlocated: 1 },
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function deferredSnapshot() {
  let resolve!: (data: FleetMapSnapshot) => void;
  const promise = new Promise<FleetMapSnapshot>((finish) => { resolve = finish; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.resetAllMocks();
  setActivePinia(createPinia());
});

describe("fleet map polling", () => {
  it("keeps a saved location when an already pending snapshot is stale", async () => {
    const store = useFleetMapStore();
    const stale = deferredSnapshot();
    const location = { latitude: 31.2, longitude: 121.5, confirmed: true };
    vi.mocked(getFleetSnapshot).mockResolvedValueOnce(snapshot()).mockReturnValueOnce(stale.promise);
    vi.mocked(updateFleetHostLocation).mockResolvedValueOnce(location);
    await store.fetchSnapshot();

    const pending = store.fetchSnapshot();
    await store.updateLocation("host", location);
    stale.resolve(snapshot());
    await pending;

    expect(store.snapshot?.hosts[0].location).toEqual(location);
    expect(store.snapshot?.counts.unlocated).toBe(0);
    expect(store.loading).toBe(false);
  });

  it("ignores a cancelled response without disrupting the next fetch", async () => {
    const store = useFleetMapStore();
    const stale = deferredSnapshot();
    const fresh = deferredSnapshot();
    vi.mocked(getFleetSnapshot).mockReturnValueOnce(stale.promise).mockReturnValueOnce(fresh.promise);
    const pending = store.fetchSnapshot();
    const signal = vi.mocked(getFleetSnapshot).mock.calls[0][0];
    store.stopPolling();
    expect(signal.aborted).toBe(true);

    const next = store.fetchSnapshot();
    stale.resolve(snapshot());
    await pending;
    expect(store.snapshot).toBeNull();
    expect(store.loading).toBe(true);

    const data = snapshot();
    data.center.confirmed = true;
    fresh.resolve(data);
    await next;
    expect(store.snapshot?.center.confirmed).toBe(true);
    expect(store.loading).toBe(false);
  });
});
