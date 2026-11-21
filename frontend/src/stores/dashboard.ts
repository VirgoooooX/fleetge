import { defineStore } from "pinia";
import { ref, computed, onScopeDispose } from "vue";
import { apiClient } from "@/api/client";
import { streamSse } from "@/api/sse";
import { createRequestId } from "@/utils/requestId";

export interface HostSummary {
  host_id: string;
  display_name: string;
  traffic_billing_day?: number;
  logo?: string | null;
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
    networkRxRate: number | null;
    networkTxRate: number | null;
    networkRxTotalBytes?: number;
    networkTxTotalBytes?: number;
    networkScope?: "host_wan" | "container" | "unknown";
    networkSelectionMode?: string;
    networkInterfaces?: string[];
    networkCounterEpoch?: string;
    counterReset?: boolean;
    hasGap?: boolean;
    diskReadBytes: number;
    diskWriteBytes: number;
    diskReadRate: number | null;
    diskWriteRate: number | null;
    loadavg: number[];
    uptime: number;
    collectorState?: "active" | "warming" | "idle";
    sampleAgeSeconds?: number;
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
  subscription?: HostSubscriptionSummary | null;
}

export interface HostSubscriptionSummary {
  configured: boolean;
  alerts_enabled?: boolean;
  provider?: string | null;
  plan_name?: string | null;
  payment_amount?: number | null;
  currency?: string;
  payment_cycle?: string | null;
  next_payment_date?: string | null;
  payment_days_remaining?: number | null;
  service_expiry_date?: string | null;
  service_days_remaining?: number | null;
  auto_renew?: boolean;
  quota_enabled?: boolean;
  traffic_direction?: string;
  traffic_quota_value?: number | null;
  traffic_quota_unit?: string | null;
  traffic_quota_bytes?: number | null;
  management_url?: string | null;
}

export interface TrafficRangeSummary {
  start: string;
  end: string;
  rxBytes: number;
  txBytes: number;
  totalBytes: number;
  hasGap: boolean;
  hasData: boolean;
}

export interface TrafficQuotaSummary {
  hostId: string;
  enabled: boolean;
  configured: boolean;
  status: "normal" | "over_quota" | "incomplete" | "unconfigured";
  billingTimezone: string;
  billingDay: number;
  periodStart?: string;
  periodEnd?: string;
  nextResetAt?: string;
  nextResetText?: string | null;
  quotaValue?: number | null;
  quotaUnit?: string;
  quotaBytes?: number | null;
  direction?: string;
  usedBytes?: number | null;
  remainingBytes?: number | null;
  overageBytes?: number | null;
  usagePercent?: number | null;
  overQuota?: boolean;
  rxBytes?: number;
  txBytes?: number;
}

export interface HostTrafficSummary {
  hostId: string;
  timezone: string;
  billingDay: number;
  today: TrafficRangeSummary;
  month: TrafficRangeSummary;
  quota?: TrafficQuotaSummary | null;
}

export interface HostTrafficState {
  summary: HostTrafficSummary | null;
  loading: boolean;
  error: string;
  updatedAt: number;
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

export interface UpdateRunItem {
  id: number;
  host_id: string;
  request_id: string;
  source: "auto" | "manual" | "bulk";
  requested_by: string;
  stack_name: string;
  status: "queued" | "running" | "success" | "partial" | "failed" | "uncertain" | "skipped";
  stage: string;
  attempts: number;
  detail: string;
  log_tail: string;
  targets_json: string;
  agent_job_id?: string | null;
  started_at: string;
  finished_at?: string | null;
}

export interface UpdateRunBatch {
  host_id: string;
  request_id: string;
  mode: string;
  items: UpdateRunItem[];
  finished: boolean;
  counts: Record<UpdateRunItem["status"], number>;
}

export interface HostUpdateRuns {
  active: UpdateRunItem[];
  recent: UpdateRunItem[];
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
  auto_update_enabled?: boolean;
  auto_update_reason?: string;
  app_url?: string;
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
  repo_digests?: string[];
  restart_count?: number;
  driver?: string;
  platform?: string;
  hostname?: string;
  domainname?: string;
  user?: string;
  working_dir?: string;
  entrypoint?: string[] | string | null;
  command?: string[] | string | null;
  restart_policy?: Record<string, any>;
  network_mode?: string;
  privileged?: boolean;
  mounts?: ContainerMount[];
  networks?: Record<string, ContainerNetwork>;
  health?: Record<string, any> | null;
}

export interface ContainerMount {
  Type?: string;
  Name?: string;
  Source?: string;
  Destination?: string;
  Mode?: string;
  RW?: boolean;
  Propagation?: string;
}

export interface ContainerNetwork {
  IPAddress?: string;
  GlobalIPv6Address?: string;
  MacAddress?: string;
  Gateway?: string;
  NetworkID?: string;
  Aliases?: string[];
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
  const trafficByHost = ref<Record<string, HostTrafficState>>({});
  const updateRunsByHost = ref<Record<string, HostUpdateRuns>>({});
  const observedUpdateRunIds = ref<Record<string, number>>({});
  const trafficRequests = new Map<string, Promise<HostTrafficSummary | null>>();
  const updateRunRequests = new Map<string, Promise<void>>();
  const updateRunRevisions = new Map<string, number>();
  const pendingUpdateSubmissions = new Map<string, string>();

  const updateCountsByHost = computed(() => {
    const counts: Record<string, number> = {};
    for (const item of updateResults.value) {
      if (item.status === "updatable") {
        counts[item.host_id] = (counts[item.host_id] || 0) + 1;
      }
    }
    return counts;
  });

  const hostsById = computed(() => new Map(hosts.value.map((host) => [host.host_id, host])));
  const onlineCount = computed(() => hosts.value.filter((h) => h.status === "online").length);
  const runningContainers = computed(() =>
    hosts.value.reduce((s, h) => s + h.container_running, 0)
  );
  const totalContainers = computed(() =>
    hosts.value.reduce((s, h) => s + h.container_total, 0)
  );
  const updateCount = computed(() =>
    hosts.value.reduce((s, h) => s + getHostUpdateCount(h.host_id), 0)
  );

  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let updateChecksPollTimer: ReturnType<typeof setInterval> | null = null;
  let updateRunPollTimer: ReturnType<typeof setInterval> | null = null;
  let updateCheckRevision = 0;
  let updateRunPollingEnabled = true;
  let disposed = false;
  let dashboardStreamController: AbortController | null = null;
  let dashboardReconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let dashboardReconnectAttempt = 0;
  let visibilityHandler: (() => void) | null = null;
  let pollingOptions: { metrics: boolean; structureInterval?: number } = { metrics: true, structureInterval: 30 };

  function applyUpdateResults(results: UpdateResult[]) {
    updateResults.value = results || [];
    updateChecksLoaded.value = true;
  }

  function upsertUpdateRunBatch(batch: UpdateRunBatch) {
    if (disposed) return;
    updateRunRevisions.set(batch.host_id, (updateRunRevisions.get(batch.host_id) || 0) + 1);
    batch.items.filter((item) => item.status === "queued" || item.status === "running")
      .forEach((item) => { observedUpdateRunIds.value[`${item.host_id}/${item.stack_name}`] = item.id; });
    const existing = updateRunsByHost.value[batch.host_id] || { active: [], recent: [] };
    const byId = new Map<number, UpdateRunItem>();
    [...existing.active, ...existing.recent, ...batch.items].forEach((item) => byId.set(item.id, item));
    const values = [...byId.values()];
    updateRunsByHost.value = {
      ...updateRunsByHost.value,
      [batch.host_id]: {
        active: values.filter((item) => item.status === "queued" || item.status === "running").sort((a, b) => a.id - b.id),
        recent: values.filter((item) => item.status !== "queued" && item.status !== "running").sort((a, b) => a.id - b.id).slice(-50),
      },
    };
    syncUpdateRunPolling();
  }

  function updateRunForStack(hostId: string, stackName: string): UpdateRunItem | null {
    const state = updateRunsByHost.value[hostId];
    if (!state) return null;
    const active = state.active.find((item) => item.stack_name === stackName);
    if (active) return active;
    let latest: UpdateRunItem | null = null;
    for (const run of state.recent) {
      if (run.stack_name === stackName && (!latest || run.id > latest.id)) latest = run;
    }
    return latest;
  }

  function updateRunBatchForRequest(hostId: string, requestId: string): UpdateRunBatch | null {
    const state = updateRunsByHost.value[hostId];
    if (!state) return null;
    const items = [...state.active, ...state.recent].filter((item) => item.request_id === requestId);
    if (!items.length) return null;
    const counts: UpdateRunBatch["counts"] = { queued: 0, running: 0, success: 0, partial: 0, failed: 0, uncertain: 0, skipped: 0 };
    items.forEach((item) => { counts[item.status] += 1; });
    return { host_id: hostId, request_id: requestId, mode: items[0].source, items, finished: counts.queued === 0 && counts.running === 0, counts };
  }

  function stopUpdateRunPolling() {
    if (updateRunPollTimer !== null) clearInterval(updateRunPollTimer);
    updateRunPollTimer = null;
  }

  function syncUpdateRunPolling() {
    if (!updateRunPollingEnabled || !Object.values(updateRunsByHost.value).some((state) => state.active.length)) {
      stopUpdateRunPolling();
      return;
    }
    if (updateRunPollTimer !== null) return;
    updateRunPollTimer = setInterval(() => {
      if (document.hidden) return;
      for (const [hostId, state] of Object.entries(updateRunsByHost.value)) {
        if (state.active.length) void fetchUpdateRuns(hostId).catch(() => undefined);
      }
    }, 2000);
  }

  async function fetchUpdateRuns(hostId: string) {
    const existing = updateRunRequests.get(hostId);
    if (existing) return existing;
    const revision = updateRunRevisions.get(hostId);
    const request = apiClient.get<HostUpdateRuns>(`/api/hosts/${encodeURIComponent(hostId)}/update-runs`)
      .then(({ data }) => {
        if (disposed || revision !== updateRunRevisions.get(hostId)) return;
        data.active.forEach((item) => {
          observedUpdateRunIds.value[`${item.host_id}/${item.stack_name}`] = item.id;
        });
        updateRunsByHost.value = {
          ...updateRunsByHost.value,
          [hostId]: data,
        };
        syncUpdateRunPolling();
      })
      .finally(() => updateRunRequests.delete(hostId));
    updateRunRequests.set(hostId, request);
    return request;
  }

  async function fetchUpdateRunBatch(hostId: string, requestId: string): Promise<UpdateRunBatch | null> {
    try {
      const response = await apiClient.get<UpdateRunBatch>(`/api/hosts/${encodeURIComponent(hostId)}/update-runs/${encodeURIComponent(requestId)}`);
      const batch = response.data;
      upsertUpdateRunBatch(batch);
      return batch;
    } catch (error: any) {
      if (error?.response?.status === 404) return null;
      throw error;
    }
  }

  async function submitUpdateRuns(hostId: string, mode: "manual" | "bulk", stackNames: string[]): Promise<UpdateRunBatch> {
    const normalizedNames = [...new Set(stackNames)];
    const submissionKey = JSON.stringify([hostId, mode, normalizedNames]);
    const requestId = pendingUpdateSubmissions.get(submissionKey) || createRequestId();
    pendingUpdateSubmissions.set(submissionKey, requestId);
    const url = `/api/hosts/${encodeURIComponent(hostId)}/update-runs`;
    try {
      let batch: UpdateRunBatch;
      try {
        const response = await apiClient.post<UpdateRunBatch>(url, { request_id: requestId, mode, stack_names: normalizedNames });
        batch = response.data;
      } catch (error) {
        const recovered = await fetchUpdateRunBatch(hostId, requestId).catch(() => null);
        if (!recovered) throw error;
        batch = recovered;
      }
      pendingUpdateSubmissions.delete(submissionKey);
      upsertUpdateRunBatch(batch);
      return batch;
    } catch (error) {
      throw Object.assign(error instanceof Error ? error : new Error(String(error)), { requestId });
    }
  }

  async function stopPendingUpdateRuns(hostId: string, requestId: string): Promise<UpdateRunBatch> {
    const response = await apiClient.post<UpdateRunBatch>(`/api/hosts/${encodeURIComponent(hostId)}/update-runs/${encodeURIComponent(requestId)}/stop-pending`);
    const batch = response.data;
    upsertUpdateRunBatch(batch);
    return batch;
  }

  function getHostUpdateCount(hostId: string) {
    if (updateChecksLoaded.value) {
      return updateCountsByHost.value[hostId] || 0;
    }
    return hostsById.value.get(hostId)?.update_count || 0;
  }

  function applyHosts(nextHosts: HostSummary[]) {
    const previous = hostsById.value;
    hosts.value = (nextHosts || []).map((host) => {
      const old = previous.get(host.host_id);
      const nextKey = host.metrics
        ? `${host.metrics.timestamp}|${host.metrics.networkCounterEpoch || "legacy"}`
        : "";
      const oldKey = old?.metrics
        ? `${old.metrics.timestamp}|${old.metrics.networkCounterEpoch || "legacy"}`
        : "";
      return old?.metrics && host.metrics && oldKey === nextKey
        ? { ...host, metrics: old.metrics }
        : host;
    });
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

  function getHostTrafficState(hostId: string): HostTrafficState {
    return trafficByHost.value[hostId] || {
      summary: null,
      loading: false,
      error: "",
      updatedAt: 0,
    };
  }

  async function fetchHostTrafficSummary(hostId: string, sync = true): Promise<HostTrafficSummary | null> {
    const pending = trafficRequests.get(hostId);
    if (pending) return pending;

    const previous = getHostTrafficState(hostId);
    trafficByHost.value = {
      ...trafficByHost.value,
      [hostId]: { ...previous, loading: true, error: "" },
    };

    const request = (async () => {
      try {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
        const response = await apiClient.get(
          `/api/hosts/${encodeURIComponent(hostId)}/traffic/summary`,
          { params: { timezone, sync } },
        );
        const summary = response.data as HostTrafficSummary;
        trafficByHost.value = {
          ...trafficByHost.value,
          [hostId]: {
            summary,
            loading: false,
            error: "",
            updatedAt: Date.now(),
          },
        };
        return summary;
      } catch (e: any) {
        const current = getHostTrafficState(hostId);
        trafficByHost.value = {
          ...trafficByHost.value,
          [hostId]: {
            ...current,
            loading: false,
            error: e?.message || "Failed to fetch traffic summary",
          },
        };
        return current.summary;
      } finally {
        trafficRequests.delete(hostId);
      }
    })();

    trafficRequests.set(hostId, request);
    return request;
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

  function startDashboardStream() {
    if (dashboardStreamController || dashboardReconnectTimer !== null || document.hidden) return;
    const { metrics, structureInterval } = pollingOptions;
    if (!metrics && !structureInterval) return;
    const controller = new AbortController();
    dashboardStreamController = controller;
    const kind = metrics ? "metrics" : "activity";
    const query = structureInterval ? `?structure_interval=${structureInterval}` : "";

    void streamSse({
      url: `/api/hosts/${kind}/stream${query}`,
      signal: controller.signal,
      onEvent: (event) => {
        if (dashboardStreamController !== controller) return;
        dashboardReconnectAttempt = 0;
        if (metrics && event.event === "hosts" && Array.isArray(event.data?.hosts)) {
          applyHosts(event.data.hosts);
          error.value = "";
        }
      },
    }).catch((reason) => {
      if (dashboardStreamController !== controller) return;
      console.warn(`${kind} stream failed:`, reason);
      if (metrics) void fetchHosts();
    }).finally(() => {
      if (dashboardStreamController !== controller) return;
      dashboardStreamController = null;
      if (document.hidden) return;
      const delay = Math.min(30000, 1000 * 2 ** dashboardReconnectAttempt);
      dashboardReconnectAttempt = Math.min(5, dashboardReconnectAttempt + 1);
      dashboardReconnectTimer = setTimeout(() => {
        dashboardReconnectTimer = null;
        startDashboardStream();
      }, delay);
    });
  }

  function stopDashboardStream() {
    dashboardStreamController?.abort();
    dashboardStreamController = null;
    if (dashboardReconnectTimer !== null) clearTimeout(dashboardReconnectTimer);
    dashboardReconnectTimer = null;
    dashboardReconnectAttempt = 0;
  }

  async function fetchUpdateChecks(includeFailures = false) {
    if (updateLoading.value) return updateResults.value;
    const revision = ++updateCheckRevision;
    updateLoading.value = true;
    try {
      const res = await apiClient.get<UpdateResult[]>("/api/update-checks", {
        params: includeFailures ? { include_failures: true } : undefined,
      });
      if (revision === updateCheckRevision && !disposed) {
        applyUpdateResults(res.data || []);
        updateCheckRunning.value = res.headers["x-update-check-running"] === "1";
      }
      return updateResults.value;
    } catch {
      return updateResults.value;
    } finally {
      if (revision === updateCheckRevision) updateLoading.value = false;
    }
  }

  async function runUpdateCheck(includeFailures = false): Promise<UpdateCheckRunState> {
    const revision = ++updateCheckRevision;
    updateLoading.value = true;
    try {
      const res = await apiClient.post<{ started: boolean; results: UpdateResult[] | null }>(
        "/api/update-checks/run",
        undefined,
        {
          params: includeFailures ? { include_failures: true } : undefined,
        },
      );
      const results = res.data.results || [];
      if (revision === updateCheckRevision && !disposed) {
        applyUpdateResults(results);
        updateCheckRunning.value = !res.data.started;
      }
      return { started: Boolean(res.data.started), results };
    } finally {
      if (revision === updateCheckRevision) updateLoading.value = false;
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

  function startPolling(options: { metrics?: boolean; structureInterval?: number } = {}) {
    stopPolling();
    updateRunPollingEnabled = true;
    syncUpdateRunPolling();
    pollingOptions = {
      metrics: options.metrics !== false,
      structureInterval: options.structureInterval,
    };
    const hostPollInterval = Math.max((options.structureInterval || 30) * 1000, 30000);

    pollTimer = setInterval(() => {
      // Pause when tab is hidden
      if (!document.hidden) {
        fetchHosts();
      }
    }, hostPollInterval);
    updateChecksPollTimer = setInterval(() => {
      if (!document.hidden) {
        fetchUpdateChecks();
      }
    }, 60000);

    visibilityHandler = () => {
      if (document.hidden) {
        stopDashboardStream();
      } else {
        fetchHosts();
        startDashboardStream();
      }
    };
    document.addEventListener("visibilitychange", visibilityHandler);

    // Load cached data instantly (GET), then stream live metrics.
    // The SSE connection triggers the backend to switch from 1h → 10s structure polling.
    fetchHosts();
    fetchUpdateChecks();
    startDashboardStream();
  }

  function stopPolling() {
    updateRunPollingEnabled = false;
    stopUpdateRunPolling();
    stopDashboardStream();
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
    if (updateChecksPollTimer) {
      clearInterval(updateChecksPollTimer);
      updateChecksPollTimer = null;
    }
    if (visibilityHandler) {
      document.removeEventListener("visibilitychange", visibilityHandler);
      visibilityHandler = null;
    }
  }

  onScopeDispose(() => {
    disposed = true;
    stopPolling();
  });

  return {
    hosts,
    hostsById,
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
    updateCount,
    updateCountsByHost,
    applyUpdateResults,
    applyHosts,
    upsertHost,
    getHostDetailCache,
    setHostDetailCache,
    patchHostDetailUpdateResults,
    hostDetailsById,
    updateRunsByHost,
    observedUpdateRunIds,
    getHostTrafficState,
    fetchHostTrafficSummary,
    getHostUpdateCount,
    fetchHosts,
    refreshHosts,
    fetchUpdateChecks,
    runUpdateCheck,
    fetchUpdateRuns,
    fetchUpdateRunBatch,
    submitUpdateRuns,
    stopPendingUpdateRuns,
    updateRunForStack,
    updateRunBatchForRequest,
    refreshAll,
    startPolling,
    stopPolling,
  };
});
