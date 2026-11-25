<template>
  <div class="detail-layout">
    <section v-if="host?.metrics" class="metrics-bar">
      <HostMetricsBar :label="t('hostCard.cpu')" :percent="host.metrics.cpuPercent" unit="%" />
      <HostMetricsBar
        :label="t('hostDetail.memory')"
        :percent="memPercent"
        :used="host.metrics.memoryUsed"
        :total="host.metrics.memoryTotal"
        unit="GB"
      />
      <HostMetricsBar
        :label="t('hostDetail.disk')"
        :percent="diskPercent"
        :used="host.metrics.diskUsed"
        :total="host.metrics.diskTotal"
        unit="GB"
      />
      <div class="metrics-item">
        <div class="metrics-header">
          <span class="metrics-label">{{ t('hostDetail.uptime') }}</span>
        </div>
        <div class="metrics-value-container">
          <span class="metrics-value">{{ uptimeText }}</span>
        </div>
      </div>
      <HostNetworkTraffic
        class="network-metrics-item"
        :host-id="hostId"
        :metrics="host.metrics"
        :traffic="trafficState"
      />
      <div class="metrics-item">
        <div class="metrics-header">
          <span class="activity-dot" :class="ioActivityLevel" />
          <span class="metrics-label">{{ t('hostDetail.diskIO') }}</span>
        </div>
        <div class="metrics-value-container telemetry-lines">
          <div class="telemetry-line">
            <span class="tl-label">R</span>
            <span class="tl-value">
              <span class="tl-amount">{{ ioReadParts.amount }}</span>
              <span class="tl-unit">{{ ioReadParts.unit }}</span>
            </span>
          </div>
          <div class="telemetry-line">
            <span class="tl-label">W</span>
            <span class="tl-value">
              <span class="tl-amount">{{ ioWriteParts.amount }}</span>
              <span class="tl-unit">{{ ioWriteParts.unit }}</span>
            </span>
          </div>
        </div>
      </div>
    </section>

    <!-- No metrics warning -->
    <el-alert
      v-else-if="host"
      :title="host.monitor?.reason || t('hostDetail.metricsUnavailable')"
      :type="host.monitor?.state === 'offline' || host.monitor?.state === 'blocked' ? 'error' : 'warning'"
      show-icon
      :closable="false"
      class="metric-warning"
    />

    <HostStackWorkspace
      v-if="host"
      :host-id="hostId"
      :stacks="stacks"
      :containers="containers"
      :container-stats="containerStats"
      :update-statuses="updateStatuses"
      :update-loading="updateLoading"
      :structure-loading="structureLoading"
      @refresh="fetchDetail"
      @check-updates="syncUpdateResults"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { fetchHostDetail, fetchUpdateResults } from "@/api/hosts";
import {
  useDashboardStore,
  type HostSummary,
  type StackSummary,
  type ContainerSummary,
  type ContainerStats,
  type UpdateResult,
} from "@/stores/dashboard";
import HostMetricsBar from "@/components/HostMetricsBar.vue";
import HostNetworkTraffic from "@/components/HostNetworkTraffic.vue";
import HostStackWorkspace from "@/components/HostStackWorkspace.vue";

const route = useRoute();
const dashboardStore = useDashboardStore();
const { t } = useI18n();
const hostId = computed(() => route.params.hostId as string);

const host = ref<HostSummary | null>(null);
const stacks = ref<StackSummary[]>([]);
const containers = ref<ContainerSummary[]>([]);
const containerStats = ref<Record<string, ContainerStats>>({});
const updateResults = ref<UpdateResult[]>([]);
const updateLoading = ref(false);

const structureLoading = ref(false);
let detailRequest: AbortController | null = null;
let updateRequest: AbortController | null = null;
const trafficState = computed(() => dashboardStore.getHostTrafficState(hostId.value));

// Computed metrics
const memPercent = computed(() => {
  if (!host.value?.metrics) return 0;
  const m = host.value.metrics;
  return m.memoryTotal > 0 ? Math.round((m.memoryUsed / m.memoryTotal) * 100) : 0;
});

const diskPercent = computed(() => {
  if (!host.value?.metrics) return 0;
  const m = host.value.metrics;
  return m.diskTotal > 0 ? Math.round((m.diskUsed / m.diskTotal) * 100) : 0;
});

const uptimeText = computed(() => {
  const seconds = host.value?.metrics?.uptime;
  if (seconds == null) return "-";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const parts: string[] = [];
  if (d > 0) parts.push(`${d} ${t('hostDetail.days')}`);
  if (h > 0) parts.push(`${h} ${t('hostDetail.hours')}`);
  if (m > 0) parts.push(`${m} ${t('hostDetail.minutes')}`);
  return parts.join(" ") || t('hostDetail.justRestarted');
});

const updateStatuses = computed(() => {
  const statuses: Record<string, string> = {};
  for (const item of updateResults.value) {
    statuses[item.image] = item.status;
  }
  return statuses;
});

function formatRateParts(bytesPerSec: number | null | undefined): { amount: string; unit: string } {
  const bytes = Math.abs(bytesPerSec || 0);
  if (bytes === 0) return { amount: "0", unit: "B/s" };

  const units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }

  return { amount: size.toFixed(1), unit: units[i] };
}

function activityLevel(totalRate: number): string {
  if (totalRate >= 10 * 1024 * 1024) return "busy";
  if (totalRate >= 512 * 1024) return "active";
  if (totalRate > 0) return "low";
  return "idle";
}

const ioReadParts = computed(() => formatRateParts(host.value?.metrics?.diskReadRate));
const ioWriteParts = computed(() => formatRateParts(host.value?.metrics?.diskWriteRate));

const ioActivityLevel = computed(() => {
  const m = host.value?.metrics;
  if (!m) return "idle";
  return activityLevel((m.diskReadRate || 0) + (m.diskWriteRate || 0));
});

function activateHostDetail(targetHostId: string) {
  const currentHost = dashboardStore.hostsById.get(targetHostId);
  host.value = currentHost || null;

  const cached = dashboardStore.getHostDetailCache(targetHostId);
  if (cached) {
    stacks.value = cached.stacks;
    containers.value = cached.containers;
    containerStats.value = cached.containerStats;
    updateResults.value = cached.updateResults;
    structureLoading.value = false;
  } else {
    stacks.value = [];
    containers.value = [];
    containerStats.value = {};
    updateResults.value = [];
    structureLoading.value = true;
  }
}

async function syncUpdateResults() {
  const requestedHostId = hostId.value;
  updateRequest?.abort();
  const request = new AbortController();
  updateRequest = request;
  updateLoading.value = true;
  try {
    const { data } = await fetchUpdateResults(request.signal);
    if (updateRequest !== request || requestedHostId !== hostId.value) return;
    dashboardStore.applyUpdateResults(data || []);
    updateResults.value = (data || []).filter((item) => item.host_id === requestedHostId);
    dashboardStore.patchHostDetailUpdateResults(requestedHostId, updateResults.value);
  } catch (error) {
    if (!request.signal.aborted) console.error("Failed to fetch update checks:", error);
  } finally {
    if (updateRequest === request) {
      updateRequest = null;
      updateLoading.value = false;
    }
  }
}

async function loadDetail(refresh = false, poll = false) {
  if (poll && detailRequest) return;
  detailRequest?.abort();
  const request = new AbortController();
  detailRequest = request;
  const requestedHostId = hostId.value;

  try {
    const { data } = await fetchHostDetail(requestedHostId, refresh, request.signal);
    if (detailRequest !== request || requestedHostId !== hostId.value) return;

    host.value = data.host || null;
    stacks.value = data.stacks || [];
    containers.value = data.containers || [];
    containerStats.value = data.container_stats || {};
    if (host.value) dashboardStore.upsertHost(host.value);

    dashboardStore.setHostDetailCache(requestedHostId, {
      host: host.value,
      stacks: stacks.value,
      containers: containers.value,
      containerStats: containerStats.value,
      updateResults: updateResults.value,
    });
    if (!poll) await syncUpdateResults();
  } catch (error) {
    if (!request.signal.aborted) console.error("Failed to fetch host detail:", error);
  } finally {
    if (detailRequest === request) {
      detailRequest = null;
      structureLoading.value = false;
    }
  }
}

function fetchDetail() {
  void loadDetail(true);
}

let pollInterval: ReturnType<typeof setInterval> | null = null;
let trafficInterval: ReturnType<typeof setInterval> | null = null;

function startPolling() {
  stopPolling();
  void dashboardStore.fetchHostTrafficSummary(hostId.value, true);
  pollInterval = setInterval(() => {
    if (!document.hidden) {
      void loadDetail(false, true);
    }
  }, 10000);
  trafficInterval = setInterval(() => {
    if (!document.hidden) {
      void dashboardStore.fetchHostTrafficSummary(hostId.value, true);
    }
  }, 60000);
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
  if (trafficInterval) {
    clearInterval(trafficInterval);
    trafficInterval = null;
  }
}

onMounted(() => {
  activateHostDetail(hostId.value);
  void loadDetail();
  startPolling();
});

watch(hostId, () => {
  cancelRequests();
  activateHostDetail(hostId.value);
  void loadDetail();
  startPolling();
});

watch(
  () => dashboardStore.hostsById.get(hostId.value),
  (nextHost) => {
    if (nextHost) {
      host.value = nextHost;
    }
  },
);

function cancelRequests() {
  detailRequest?.abort();
  detailRequest = null;
  updateRequest?.abort();
  updateRequest = null;
  updateLoading.value = false;
}

onUnmounted(() => {
  cancelRequests();
  stopPolling();
});
</script>

<style scoped>
.detail-layout {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.detail-layout :deep(.host-workspace) {
  flex: 1;
  min-height: 0;
}
.metrics-bar {
  display: grid;
  grid-template-columns: repeat(8, minmax(0, 1fr));
  gap: 1px;
  border: 1px solid var(--border-subtle);
  background: var(--border-subtle);
  border-radius: var(--ui-radius-lg);
  overflow: hidden;
}
.network-metrics-item {
  grid-column: span 3;
}
.metrics-item {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 12px;
  background: var(--surface-panel);
}
.metrics-header {
  display: flex;
  align-items: center;
  gap: 6px;
}
.metrics-label {
  font-size: var(--text-sm);
  color: var(--text-secondary);
  font-weight: 600;
}
.metrics-value-container {
  display: flex;
  justify-content: flex-end;
  align-items: flex-end;
  min-height: 26px;
}
.metrics-value {
  font-size: var(--text-md);
  color: var(--text-primary);
  font-weight: 600;
  text-align: right;
}
.telemetry-lines {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.telemetry-line {
  display: grid;
  grid-template-columns: 14px max-content;
  justify-content: end;
  align-items: center;
  gap: 3px;
}
.tl-label {
  font-family: var(--font-body);
  font-size: var(--text-sm);
  color: var(--text-muted);
  text-align: center;
  user-select: none;
}
.tl-value {
  display: grid;
  grid-template-columns: 6.5ch 4.4ch;
  justify-content: end;
  align-items: baseline;
  gap: 2px;
  font-family: var(--font-body);
  font-variant-numeric: tabular-nums;
  font-size: var(--text-sm);
  color: var(--text-primary);
  white-space: nowrap;
}
.tl-amount {
  min-width: 6.5ch;
  text-align: right;
}
.tl-unit {
  min-width: 4.4ch;
  color: var(--text-secondary);
  text-align: left;
}

.activity-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.activity-dot.idle { background: var(--text-muted); }
.activity-dot.low { background: var(--accent-cyan); }
.activity-dot.active { background: var(--warning); }
.activity-dot.busy { background: var(--danger); }
.metric-warning {
  margin-bottom: 16px;
}

@media (max-width: 900px) {
  .metrics-bar {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .network-metrics-item {
    grid-column: span 2;
  }
  .metrics-bar > *:last-child {
    grid-column: span 2;
  }
}
</style>
