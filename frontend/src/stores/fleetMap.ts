import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { apiClient } from "@/api/client";
import { useDashboardStore } from "@/stores/dashboard";
import { filterFleetHosts } from "@/utils/fleetMap";
import { t } from "@/i18n";

export interface FleetLocation {
  latitude: number;
  longitude: number;
  city?: string | null;
  region?: string | null;
  country?: string | null;
  country_code?: string | null;
  source?: string | null;
  confirmed: boolean;
  confidence?: string | null;
}

export interface NetworkIdentityEvidence {
  observedAt?: string;
  effectiveIp?: string | null;
  effectiveSource?: string | null;
  confidence?: string;
  conflict?: boolean;
  locationDrift?: boolean;
  fixedOverride?: string | null;
  categories?: Record<string, {
    status?: string;
    addresses?: string[];
    eligibleAddresses?: string[];
    eligible?: boolean;
    mode?: string;
    excludedReason?: string | null;
    excludedReasons?: string[];
    cnameChain?: string[];
  }>;
}

export interface FleetLocationSearchResult extends FleetLocation {
  name: string;
}

export interface FleetMapStackService {
  name: string;
  container_id?: string;
  state: string;
  status: string;
  health?: Record<string, unknown> | null;
}

export interface FleetMapStack {
  name: string;
  status: string;
  service_count: number;
  running_count: number;
  services: FleetMapStackService[];
}

export interface FleetMapHost {
  host_id: string;
  display_name: string;
  enabled: boolean;
  status: "online" | "degraded" | "offline" | "unknown";
  metrics?: Record<string, any> | null;
  container_count: number;
  last_seen?: string | null;
  error_message?: string | null;
  agent_instance_id?: string | null;
  location?: FleetLocation | null;
  network_identity?: NetworkIdentityEvidence | null;
  stacks: FleetMapStack[];
}

export interface FleetMapSnapshot {
  center: {
    name: string;
    city?: string | null;
    region?: string | null;
    country?: string | null;
    country_code?: string | null;
    latitude: number;
    longitude: number;
    confirmed: boolean;
  };
  hosts: FleetMapHost[];
  counts: { total: number; online: number; degraded: number; offline: number; unlocated: number };
  updated_at: string;
}

export const useFleetMapStore = defineStore("fleet-map", () => {
  const snapshot = ref<FleetMapSnapshot | null>(null);
  const loading = ref(false);
  const error = ref("");
  const filter = ref<"all" | "online" | "degraded" | "offline" | "unlocated">("all");
  const onlyIssues = ref(false);
  let timer: ReturnType<typeof setInterval> | null = null;

  const hosts = computed(() => {
    const all = snapshot.value?.hosts || [];
    return filterFleetHosts(all, filter.value, onlyIssues.value);
  });

  const unlocatedHosts = computed(() => (snapshot.value?.hosts || []).filter((host) => !host.location));

  async function fetchSnapshot() {
    if (loading.value) return;
    loading.value = true;
    error.value = "";
    try {
      const res = await apiClient.get("/api/fleet-map");
      snapshot.value = res.data;
      const dashboard = useDashboardStore();
      const byId = new Map(dashboard.hosts.map((host) => [host.host_id, host]));
      const currentSnapshot = snapshot.value as FleetMapSnapshot;
      currentSnapshot.hosts = currentSnapshot.hosts.map((host) => {
        const live = byId.get(host.host_id);
        return live
          ? { ...host, status: live.status, metrics: live.metrics, container_count: live.container_total, error_message: live.error_message }
          : host;
      });
    } catch (e: any) {
      error.value = e.response?.data?.detail || e.message || t("map.loadFailed");
    } finally {
      loading.value = false;
    }
  }

  async function fetchCenterSettings() {
    const res = await apiClient.get("/api/admin/fleet-map/settings");
    return res.data;
  }

  async function suggestCenterLocation() {
    const res = await apiClient.post("/api/admin/fleet-map/settings/suggest");
    return res.data as FleetLocation;
  }

  async function saveCenterSettings(data: {
    name: string;
    city?: string;
    region?: string;
    country?: string;
    country_code?: string;
    latitude: number;
    longitude: number;
    confirmed: boolean;
  }) {
    const res = await apiClient.put("/api/admin/fleet-map/settings", data);
    if (snapshot.value) snapshot.value.center = res.data;
    return res.data;
  }

  async function updateLocation(hostId: string, location: FleetLocation) {
    const res = await apiClient.put("/api/admin/hosts/" + hostId + "/location", location);
    if (snapshot.value) {
      const host = snapshot.value.hosts.find((item) => item.host_id === hostId);
      if (host) {
        host.location = res.data.location;
        snapshot.value.counts.unlocated = snapshot.value.hosts.filter((item) => !item.location).length;
      }
    }
    return res.data.location;
  }

  async function suggestLocation(hostId: string) {
    const res = await apiClient.post("/api/admin/hosts/" + hostId + "/location/suggest");
    if (snapshot.value) {
      const host = snapshot.value.hosts.find((item) => item.host_id === hostId);
      if (host) {
        host.location = res.data.location;
        snapshot.value.counts.unlocated = snapshot.value.hosts.filter((item) => !item.location).length;
      }
    }
    return res.data.location as FleetLocation;
  }

  async function refreshNetworkIdentity(hostId: string, force = true) {
    const res = await apiClient.post(
      `/api/admin/hosts/${encodeURIComponent(hostId)}/network-identity/refresh`,
      undefined,
      { params: { force } },
    );
    if (snapshot.value) {
      const host = snapshot.value.hosts.find((item) => item.host_id === hostId);
      if (host) host.network_identity = res.data;
    }
    return res.data as NetworkIdentityEvidence;
  }

  async function setNetworkIdentityOverride(hostId: string, ip: string | null) {
    const res = await apiClient.put(
      `/api/admin/hosts/${encodeURIComponent(hostId)}/network-identity/override`,
      { ip },
    );
    if (snapshot.value) {
      const host = snapshot.value.hosts.find((item) => item.host_id === hostId);
      if (host) host.network_identity = { ...res.data, fixedOverride: ip };
    }
    return res.data as NetworkIdentityEvidence;
  }

  async function searchLocations(query: string, language = "zh") {
    const res = await apiClient.get("/api/admin/location/search", {
      params: { q: query, language },
    });
    return (res.data.results || []) as FleetLocationSearchResult[];
  }

  function startPolling() {
    stopPolling();
    void fetchSnapshot();
    timer = setInterval(() => {
      if (!document.hidden) void fetchSnapshot();
    }, 15000);
  }

  function stopPolling() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  return {
    snapshot, loading, error, filter, onlyIssues, hosts, unlocatedHosts,
    fetchSnapshot, fetchCenterSettings, suggestCenterLocation, saveCenterSettings, updateLocation,
    suggestLocation, searchLocations, startPolling, stopPolling,
    refreshNetworkIdentity, setNetworkIdentityOverride,
  };
});
