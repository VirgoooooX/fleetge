import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { apiClient } from "@/api/client";
import { streamSse } from "@/api/sse";

export interface HostSummary {
  host_id: string;
  display_name: string;
  status: "online" | "offline" | "degraded" | "unknown";
  metrics?: {
    hostname: string;
    timestamp: string;
    cpuPercent: number;
    memoryUsed: number;
    memoryTotal: number;
    diskUsed: number;
    diskTotal: number;
    networkRxBytes: number;
    networkTxBytes: number;
    networkRxRate: number;
    networkTxRate: number;
    diskReadBytes: number;
    diskWriteBytes: number;
    diskReadRate: number;
    diskWriteRate: number;
    loadavg: number[];
    uptime: number;
  };
  docker_version?: string;
  api_version?: string;
  os_info?: string;
  architecture?: string;
  docker_root_dir?: string;
  container_running: number;
  container_stopped: number;
  container_total: number;
  image_count: number;
  docker_disk_images?: number;
  docker_disk_containers?: number;
  docker_disk_volumes?: number;
  docker_disk_build_cache?: number;
  update_count: number;
}

export interface UpdateResult {
  host_id: string;
  image: string;
  current_digest?: string;
  registry_digest?: string;
  status: string;
}

export const useDashboardStore = defineStore("dashboard", () => {
  const hosts = ref<HostSummary[]>([]);
  const updateResults = ref<UpdateResult[]>([]);
  const updateChecksLoaded = ref(false);
  const loading = ref(false);
  const updateLoading = ref(false);
  const error = ref("");

  const updateCountsByHost = computed(() => {
    const counts: Record<string, number> = {};
    for (const item of updateResults.value) {
      if (item.status === "updatable") {
        counts[item.host_id] = (counts[item.host_id] || 0) + 1;
      }
    }
    return counts;
  });

  const onlineCount = computed(() => hosts.value.filter((h) => h.status === "online").length);
  const runningContainers = computed(() =>
    hosts.value.reduce((s, h) => s + h.container_running, 0)
  );
  const totalContainers = computed(() =>
    hosts.value.reduce((s, h) => s + h.container_total, 0)
  );
  const totalStacks = computed(() => 0); // Will be populated via detail
  const updateCount = computed(() =>
    hosts.value.reduce((s, h) => s + getHostUpdateCount(h.host_id), 0)
  );

  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let updatePollTimer: ReturnType<typeof setTimeout> | null = null;
  let metricsStreamController: AbortController | null = null;
  let visibilityHandler: (() => void) | null = null;

  function applyUpdateResults(results: UpdateResult[]) {
    updateResults.value = results || [];
    updateChecksLoaded.value = true;
  }

  function getHostUpdateCount(hostId: string) {
    if (updateChecksLoaded.value) {
      return updateCountsByHost.value[hostId] || 0;
    }
    const host = hosts.value.find((h) => h.host_id === hostId);
    return host?.update_count || 0;
  }

  function applyHosts(nextHosts: HostSummary[]) {
    hosts.value = nextHosts || [];
  }

  function upsertHost(nextHost: HostSummary) {
    const index = hosts.value.findIndex((host) => host.host_id === nextHost.host_id);
    if (index === -1) {
      hosts.value = [...hosts.value, nextHost];
    } else {
      hosts.value = [
        ...hosts.value.slice(0, index),
        nextHost,
        ...hosts.value.slice(index + 1),
      ];
    }
  }

  async function fetchHosts() {
    if (loading.value) return;
    loading.value = true;
    error.value = "";
    try {
      const res = await apiClient.get("/api/hosts");
      applyHosts(res.data.hosts || []);
    } catch (e: any) {
      error.value = e.message || "Failed to fetch hosts";
    } finally {
      loading.value = false;
    }
  }

  async function refreshHosts() {
    if (loading.value) return;
    loading.value = true;
    error.value = "";
    try {
      const res = await apiClient.post("/api/hosts/refresh");
      applyHosts(res.data.hosts || []);
    } catch (e: any) {
      error.value = e.message || "Failed to refresh hosts";
    } finally {
      loading.value = false;
    }
  }

  function startMetricsStream() {
    if (metricsStreamController || document.hidden) return;

    const controller = new AbortController();
    metricsStreamController = controller;

    void streamSse({
      url: "/api/hosts/metrics/stream",
      signal: controller.signal,
      onEvent: (ev) => {
        if (ev.event !== "hosts") return;
        const nextHosts = ev.data?.hosts;
        if (Array.isArray(nextHosts)) {
          applyHosts(nextHosts);
          error.value = "";
        }
      },
    })
      .catch((e: any) => {
        if (controller.signal.aborted) return;
        console.warn("Metrics stream failed:", e);
        fetchHosts();
      })
      .finally(() => {
        if (metricsStreamController === controller) {
          metricsStreamController = null;
        }
      });
  }

  function stopMetricsStream() {
    if (metricsStreamController) {
      metricsStreamController.abort();
      metricsStreamController = null;
    }
  }

  async function fetchUpdateChecks() {
    if (updateLoading.value) return updateResults.value;
    updateLoading.value = true;
    try {
      const res = await apiClient.get("/api/update-checks");
      applyUpdateResults(res.data || []);
      return updateResults.value;
    } catch {
      return updateResults.value;
    } finally {
      updateLoading.value = false;
    }
  }

  async function runUpdateCheck() {
    updateLoading.value = true;
    try {
      const res = await apiClient.post("/api/update-checks/run");
      applyUpdateResults(res.data.results || []);
      return updateResults.value;
    } finally {
      updateLoading.value = false;
    }
  }

  async function refreshAll() {
    await Promise.all([refreshHosts(), fetchUpdateChecks()]);
  }

  function startPolling(intervalMs = 15000) {
    stopPolling();
    const hostPollInterval = Math.max(intervalMs, 15000);

    pollTimer = setInterval(() => {
      // Pause when tab is hidden
      if (!document.hidden) {
        refreshHosts();
      }
    }, hostPollInterval);
    updatePollTimer = setInterval(() => {
      if (!document.hidden) {
        fetchUpdateChecks();
      }
    }, Math.max(intervalMs, 60000));

    visibilityHandler = () => {
      if (document.hidden) {
        stopMetricsStream();
      } else {
        refreshHosts();
        startMetricsStream();
      }
    };
    document.addEventListener("visibilitychange", visibilityHandler);

    refreshAll();
    startMetricsStream();
  }

  function stopPolling() {
    stopMetricsStream();
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    if (updatePollTimer) {
      clearInterval(updatePollTimer);
      updatePollTimer = null;
    }
    if (visibilityHandler) {
      document.removeEventListener("visibilitychange", visibilityHandler);
      visibilityHandler = null;
    }
  }

  return {
    hosts,
    updateResults,
    updateChecksLoaded,
    loading,
    updateLoading,
    error,
    onlineCount,
    runningContainers,
    totalContainers,
    totalStacks,
    updateCount,
    updateCountsByHost,
    applyUpdateResults,
    applyHosts,
    upsertHost,
    getHostUpdateCount,
    fetchHosts,
    refreshHosts,
    fetchUpdateChecks,
    runUpdateCheck,
    refreshAll,
    startPolling,
    stopPolling,
  };
});
