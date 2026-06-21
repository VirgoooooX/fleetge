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
  error_message?: string;
}

export interface UpdateResult {
  host_id: string;
  image: string;
  current_digest?: string;
  registry_digest?: string;
  failure_count?: number;
  last_failure_status?: string;
  last_failure_http_status?: number;
  last_failure_retry_after?: number;
  last_failure_at?: string;
  status: string;
}

export interface UpdateCheckRunState {
  started: boolean;
  results: UpdateResult[];
}

export interface StackService {
  name: string;
  container_id?: string;
  state: string;
  status: string;
}

export interface StackSummary {
  name: string;
  status: string;
  compose_file?: string;
  service_count: number;
  running_count: number;
  services: StackService[];
  icon_url?: string;
  management_status?: string;
}

export interface ContainerPort {
  private_port: number;
  public_port?: number;
  ip?: string;
  type: string;
}

export interface ContainerSummary {
  id: string;
  name: string;
  image: string;
  state: string;
  status: string;
  created: number;
  ports: ContainerPort[];
  stack_name?: string;
  service_name?: string;
  labels?: Record<string, string>;
  image_id?: string;
}

export interface ContainerStats {
  cpu_percent: number;
  memory_usage: number;
  memory_limit: number;
  memory_percent: number;
  network_rx_bytes: number;
  network_tx_bytes: number;
  block_read_bytes: number;
  block_write_bytes: number;
}

export interface HostDetailCache {
  host: HostSummary | null;
  stacks: StackSummary[];
  containers: ContainerSummary[];
  containerStats: Record<string, ContainerStats>;
  updateResults: UpdateResult[];
  cachedAt: number;
}

export const useDashboardStore = defineStore("dashboard", () => {
  const hosts = ref<HostSummary[]>([]);
  const updateResults = ref<UpdateResult[]>([]);
  const updateChecksLoaded = ref(false);
  const loading = ref(false);
  const updateLoading = ref(false);
  const updateCheckRunning = ref(false);
  const error = ref("");
  const manualLoading = ref(false);
  const hostDetailsById = ref<Record<string, HostDetailCache>>({});

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

  function getHostDetailCache(hostId: string): HostDetailCache | null {
    return hostDetailsById.value[hostId] || null;
  }

  function setHostDetailCache(hostId: string, detail: Omit<HostDetailCache, "cachedAt">) {
    hostDetailsById.value = {
      ...hostDetailsById.value,
      [hostId]: {
        ...detail,
        cachedAt: Date.now(),
      },
    };
  }

  function patchHostDetailUpdateResults(hostId: string, newResults: UpdateResult[]) {
    const cached = hostDetailsById.value[hostId];
    if (!cached) return;
    hostDetailsById.value = {
      ...hostDetailsById.value,
      [hostId]: {
        ...cached,
        updateResults: newResults,
        cachedAt: Date.now(),
      },
    };
  }

  async function fetchHosts() {
    if (loading.value) return;
    loading.value = true;
    error.value = "";
    try {
      const res = await apiClient.get("/api/hosts");
      applyHosts(res.data.hosts || []);
    } catch (e: any) {
      const msg = e.message || "Failed to fetch hosts";
      if (!/(timeout|network|econnaborted)/i.test(msg)) {
        error.value = msg;
      }
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
      const msg = e.message || "Failed to refresh hosts";
      if (!/(timeout|network|econnaborted)/i.test(msg)) {
        error.value = msg;
      }
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

  async function fetchUpdateChecks(includeFailures = false) {
    if (updateLoading.value) return updateResults.value;
    updateLoading.value = true;
    try {
      const res = await apiClient.get("/api/update-checks", {
        params: includeFailures ? { include_failures: true } : undefined,
      });
      applyUpdateResults(res.data || []);
      updateCheckRunning.value = res.headers["x-update-check-running"] === "1";
      return updateResults.value;
    } catch {
      return updateResults.value;
    } finally {
      updateLoading.value = false;
    }
  }

  async function runUpdateCheck(includeFailures = false): Promise<UpdateCheckRunState> {
    updateLoading.value = true;
    try {
      const res = await apiClient.post(
        "/api/update-checks/run",
        undefined,
        {
          params: includeFailures ? { include_failures: true } : undefined,
        },
      );
      applyUpdateResults(res.data.results || []);
      updateCheckRunning.value = !res.data.started;
      return {
        started: Boolean(res.data.started),
        results: updateResults.value,
      };
    } finally {
      updateLoading.value = false;
    }
  }

  async function refreshAll() {
    manualLoading.value = true;
    try {
      await Promise.all([refreshHosts(), fetchUpdateChecks()]);
    } finally {
      manualLoading.value = false;
    }
  }

  function startPolling(intervalMs = 15000) {
    stopPolling();
    const hostPollInterval = Math.max(intervalMs, 15000);

    pollTimer = setInterval(() => {
      // Pause when tab is hidden
      if (!document.hidden) {
        fetchHosts();
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
        fetchHosts();
        startMetricsStream();
      }
    };
    document.addEventListener("visibilitychange", visibilityHandler);

    // Load cached data instantly (GET), then stream live metrics.
    // The SSE connection triggers the backend to switch from 1h → 10s structure polling.
    fetchHosts();
    fetchUpdateChecks();
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
    updateCheckRunning,
    manualLoading,
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
    getHostDetailCache,
    setHostDetailCache,
    patchHostDetailUpdateResults,
    hostDetailsById,
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
