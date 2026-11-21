import { defineStore } from "pinia";
import { computed, onScopeDispose, ref } from "vue";
import {
  fleetRequestError, getFleetCenterSettings, getFleetSnapshot, refreshFleetNetworkIdentity,
  searchFleetLocations, suggestFleetCenterLocation, suggestFleetHostLocation, updateFleetCenter,
  updateFleetHostLocation, updateFleetNetworkIdentityOverride,
  type FleetLocation, type FleetMapCenter, type FleetMapSnapshot,
} from "@/api/fleetMap";
import { filterFleetHosts, type FleetMapFilter } from "@/utils/fleetMap";
import { t } from "@/i18n";

export type {
  FleetLocation, FleetLocationSearchResult, FleetMapHost, FleetMapSnapshot,
  FleetMapStack, FleetMapStackService, NetworkIdentityEvidence,
} from "@/api/fleetMap";

export const useFleetMapStore = defineStore("fleet-map", () => {
  const snapshot = ref<FleetMapSnapshot | null>(null);
  const loading = ref(false);
  const error = ref("");
  const filter = ref<FleetMapFilter>("all");
  const onlyIssues = ref(false);
  let timer: ReturnType<typeof setInterval> | undefined;
  let activeRequest: AbortController | undefined;
  let mutationRevision = 0;

  const hosts = computed(() => filterFleetHosts(snapshot.value?.hosts ?? [], filter.value, onlyIssues.value));
  const unlocatedHosts = computed(() => (snapshot.value?.hosts ?? []).filter((host) => !host.location));

  async function fetchSnapshot() {
    if (activeRequest) return;
    const request = new AbortController();
    const revision = mutationRevision;
    activeRequest = request;
    loading.value = true;
    error.value = "";
    try {
      const data = await getFleetSnapshot(request.signal);
      // A response started before a mutation may carry the old location or identity.
      if (activeRequest === request && revision === mutationRevision) snapshot.value = data;
    } catch (cause) {
      if (activeRequest === request) error.value = fleetRequestError(cause, true) || t("map.loadFailed");
    } finally {
      if (activeRequest === request) {
        activeRequest = undefined;
        loading.value = false;
      }
    }
  }

  async function saveCenterSettings(data: FleetMapCenter) {
    const center = await updateFleetCenter(data);
    mutationRevision++;
    if (snapshot.value) snapshot.value.center = center;
    return center;
  }

  function applyHostLocation(hostId: string, location: FleetLocation, onlyUnconfirmed = false) {
    mutationRevision++;
    const current = snapshot.value;
    const host = current?.hosts.find((item) => item.host_id === hostId);
    if (host && current && (!onlyUnconfirmed || !host.location?.confirmed)) {
      host.location = location;
      current.counts.unlocated = unlocatedHosts.value.length;
    }
  }

  async function updateLocation(hostId: string, data: FleetLocation) {
    const location = await updateFleetHostLocation(hostId, data);
    applyHostLocation(hostId, location);
    return location;
  }

  async function suggestLocation(hostId: string) {
    const location = await suggestFleetHostLocation(hostId);
    applyHostLocation(hostId, location, true);
    return location;
  }

  async function refreshNetworkIdentity(hostId: string, force = true, signal?: AbortSignal) {
    const evidence = await refreshFleetNetworkIdentity(hostId, force, signal);
    if (signal?.aborted) return evidence;
    mutationRevision++;
    const host = snapshot.value?.hosts.find((item) => item.host_id === hostId);
    if (host) host.network_identity = evidence;
    return evidence;
  }

  async function setNetworkIdentityOverride(hostId: string, ip: string | null) {
    const evidence = await updateFleetNetworkIdentityOverride(hostId, ip);
    mutationRevision++;
    const host = snapshot.value?.hosts.find((item) => item.host_id === hostId);
    if (host) host.network_identity = { ...evidence, fixedOverride: ip };
    return evidence;
  }

  function startPolling() {
    if (timer !== undefined) return;
    void fetchSnapshot();
    timer = setInterval(() => {
      if (!document.hidden) void fetchSnapshot();
    }, 15000);
  }

  function stopPolling() {
    clearInterval(timer);
    timer = undefined;
    const request = activeRequest;
    activeRequest = undefined;
    request?.abort();
    loading.value = false;
  }

  onScopeDispose(stopPolling);

  return {
    snapshot, loading, error, filter, onlyIssues, hosts, unlocatedHosts,
    fetchSnapshot, fetchCenterSettings: getFleetCenterSettings, suggestCenterLocation: suggestFleetCenterLocation,
    saveCenterSettings, updateLocation, suggestLocation, searchLocations: searchFleetLocations,
    startPolling, stopPolling, refreshNetworkIdentity, setNetworkIdentityOverride,
  };
});
