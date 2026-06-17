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
          <span class="metrics-label">{{ t('hostDetail.load') }}</span>
        </div>
        <div class="metrics-value-container">
          <span class="metrics-value font-mono">{{ loadText }}</span>
        </div>
      </div>
      <div class="metrics-item">
        <div class="metrics-header">
          <span class="metrics-label">{{ t('hostDetail.uptime') }}</span>
        </div>
        <div class="metrics-value-container">
          <span class="metrics-value">{{ uptimeText }}</span>
        </div>
      </div>
      <div class="metrics-item">
        <div class="metrics-header">
          <span class="activity-dot" :class="netActivityLevel" />
          <span class="metrics-label">{{ t('hostDetail.network') }}</span>
        </div>
        <div class="metrics-value-container telemetry-lines">
          <div class="telemetry-line">
            <span class="tl-label">↓</span>
            <span class="tl-value">
              <span class="tl-amount">{{ netRxParts.amount }}</span>
              <span class="tl-unit">{{ netRxParts.unit }}</span>
            </span>
          </div>
          <div class="telemetry-line">
            <span class="tl-label">↑</span>
            <span class="tl-value">
              <span class="tl-amount">{{ netTxParts.amount }}</span>
              <span class="tl-unit">{{ netTxParts.unit }}</span>
            </span>
          </div>
        </div>
      </div>
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
    <el-alert v-else-if="host" :title="t('hostDetail.metricsUnavailable')" type="warning" show-icon :closable="false" class="metric-warning" />

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
      @check-updates="runUpdateCheck"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { useRoute } from "vue-router";
import { useI18n } from "vue-i18n";
import { apiClient } from "@/api/client";
import {
  useDashboardStore,
  type HostSummary,
  type StackSummary,
  type ContainerSummary,
  type ContainerStats,
  type UpdateResult,
} from "@/stores/dashboard";
import HostMetricsBar from "@/components/HostMetricsBar.vue";
import HostStackWorkspace from "@/components/HostStackWorkspace.vue";

const route = useRoute();
const dashboardStore = useDashboardStore();
const { t } = useI18n();
const hostId = computed(() => route.params.hostId as string);

const loading = ref(true);
const host = ref<HostSummary | null>(null);
const stacks = ref<StackSummary[]>([]);
const containers = ref<ContainerSummary[]>([]);
const containerStats = ref<Record<string, ContainerStats>>({});
const updateResults = ref<UpdateResult[]>([]);
const updateLoading = ref(false);

const structureLoading = ref(false);
const detailRequestSeq = ref(0);

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

const loadText = computed(() => {
  const l = host.value?.metrics?.loadavg;
  if (!l || l.length === 0) return "-";
  return l.map((x) => x.toFixed(2)).join(" / ");
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

function formatRate(bytesPerSec: number): string {
  if (!bytesPerSec) return "0 B/s";
  const abs = Math.abs(bytesPerSec);
  const units = ["B/s", "KB/s", "MB/s", "GB/s"];
  let i = 0;
  let size = abs;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }
  return `${size.toFixed(1)}${units[i]}`;
}

function formatRateParts(bytesPerSec: number | undefined): { amount: string; unit: string } {
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

const netRxParts = computed(() => formatRateParts(host.value?.metrics?.networkRxRate));
const netTxParts = computed(() => formatRateParts(host.value?.metrics?.networkTxRate));
const ioReadParts = computed(() => formatRateParts(host.value?.metrics?.diskReadRate));
const ioWriteParts = computed(() => formatRateParts(host.value?.metrics?.diskWriteRate));

const netActivityLevel = computed(() => {
  const m = host.value?.metrics;
  if (!m) return "idle";
  return activityLevel((m.networkRxRate || 0) + (m.networkTxRate || 0));
});

const ioActivityLevel = computed(() => {
  const m = host.value?.metrics;
  if (!m) return "idle";
  return activityLevel((m.diskReadRate || 0) + (m.diskWriteRate || 0));
});

function activateHostDetail(targetHostId: string) {
  const currentHost = dashboardStore.hosts.find(
    (item) => item.host_id === targetHostId
  );
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

function applyUpdateResults(results: UpdateResult[], targetHostId = hostId.value): UpdateResult[] {
  dashboardStore.applyUpdateResults(results || []);
  const filteredResults = (results || []).filter(
    (item) => item.host_id === targetHostId
  );
  if (targetHostId === hostId.value) {
    updateResults.value = filteredResults;
  }
  return filteredResults;
}

async function fetchUpdateResults(targetHostId = hostId.value): Promise<UpdateResult[]> {
  updateLoading.value = true;
  try {
    const res = await apiClient.get("/api/update-checks");
    return applyUpdateResults(res.data || [], targetHostId);
  } catch (e) {
    console.error("Failed to fetch update checks:", e);
    if (targetHostId === hostId.value) {
      updateResults.value = [];
    }
    return [];
  } finally {
    if (targetHostId === hostId.value) {
      updateLoading.value = false;
    }
  }
}

async function runUpdateCheck() {
  const requestedHostId = hostId.value;
  updateLoading.value = true;
  try {
    const results = await dashboardStore.runUpdateCheck();
    applyUpdateResults(results || [], requestedHostId);
    if (requestedHostId !== hostId.value) return;
    await fetchDetail({ skipUpdates: true });
  } catch (e) {
    console.error("Failed to run update check:", e);
  } finally {
    if (requestedHostId === hostId.value) {
      updateLoading.value = false;
    }
  }
}

async function fetchDetailCached(options: { skipUpdates?: boolean; silent?: boolean } = {}) {
  const requestId = ++detailRequestSeq.value;
  const requestedHostId = hostId.value;

  if (!options.silent) {
    loading.value = true;
  }
  try {
    const res = await apiClient.get(
      `/api/hosts/${encodeURIComponent(hostId.value)}`
    );

    if (requestId !== detailRequestSeq.value || requestedHostId !== hostId.value) return;

    host.value = res.data.host || null;
    stacks.value = res.data.stacks || [];
    containers.value = res.data.containers || [];
    containerStats.value = res.data.container_stats || {};

    if (host.value) {
      dashboardStore.upsertHost(host.value);
    }

    dashboardStore.setHostDetailCache(requestedHostId, {
      host: host.value,
      stacks: stacks.value,
      containers: containers.value,
      containerStats: containerStats.value,
      updateResults: options.skipUpdates
        ? (dashboardStore.getHostDetailCache(requestedHostId)?.updateResults || [])
        : updateResults.value,
    });

    if (!options.skipUpdates) {
      const fetchedUpdateResults = await fetchUpdateResults(requestedHostId);
      if (requestId === detailRequestSeq.value && requestedHostId === hostId.value) {
        dashboardStore.patchHostDetailUpdateResults(requestedHostId, fetchedUpdateResults);
      }
    }
  } catch (e: any) {
    if (requestId !== detailRequestSeq.value || requestedHostId !== hostId.value) return;
    console.error("Failed to fetch host detail:", e);
  } finally {
    if (requestId === detailRequestSeq.value && requestedHostId === hostId.value) {
      structureLoading.value = false;
      if (!options.silent) {
        loading.value = false;
      }
    }
  }
}

async function fetchDetail(options: { skipUpdates?: boolean; silent?: boolean } = {}) {
  const requestId = ++detailRequestSeq.value;
  const requestedHostId = hostId.value;

  if (!options.silent) {
    loading.value = true;
  }
  try {
    const res = await apiClient.post(
      `/api/hosts/${encodeURIComponent(hostId.value)}/refresh`
    );

    if (requestId !== detailRequestSeq.value || requestedHostId !== hostId.value) return;

    host.value = res.data.host || null;
    stacks.value = res.data.stacks || [];
    containers.value = res.data.containers || [];
    containerStats.value = res.data.container_stats || {};

    if (host.value) {
      dashboardStore.upsertHost(host.value);
    }

    dashboardStore.setHostDetailCache(requestedHostId, {
      host: host.value,
      stacks: stacks.value,
      containers: containers.value,
      containerStats: containerStats.value,
      updateResults: options.skipUpdates
        ? (dashboardStore.getHostDetailCache(requestedHostId)?.updateResults || [])
        : updateResults.value,
    });

    if (!options.skipUpdates) {
      const fetchedUpdateResults = await fetchUpdateResults(requestedHostId);
      if (requestId === detailRequestSeq.value && requestedHostId === hostId.value) {
        dashboardStore.patchHostDetailUpdateResults(requestedHostId, fetchedUpdateResults);
      }
    }
  } catch (e: any) {
    if (requestId !== detailRequestSeq.value || requestedHostId !== hostId.value) return;
    console.error("Failed to fetch host detail:", e);
  } finally {
    if (requestId === detailRequestSeq.value && requestedHostId === hostId.value) {
      structureLoading.value = false;
      if (!options.silent) {
        loading.value = false;
      }
    }
  }
}

let pollInterval: any = null;

function startPolling() {
  stopPolling();
  pollInterval = setInterval(() => {
    if (!document.hidden) {
      fetchDetailCached({ skipUpdates: true, silent: true });
    }
  }, 10000);
}

function stopPolling() {
  if (pollInterval) {
    clearInterval(pollInterval);
    pollInterval = null;
  }
}

onMounted(() => {
  activateHostDetail(hostId.value);
  fetchDetailCached();
  startPolling();
});

watch(hostId, () => {
  activateHostDetail(hostId.value);
  fetchDetailCached();
  startPolling();
});

watch(
  () => dashboardStore.hosts.find((item) => item.host_id === hostId.value),
  (nextHost) => {
    if (nextHost) {
      host.value = nextHost;
    }
  },
  { deep: true }
);

onUnmounted(() => {
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
  grid-template-columns: repeat(7, minmax(0, 1fr));
  gap: 1px;
  border: 1px solid var(--border-subtle);
  background: var(--border-subtle);
  border-radius: 8px;
  overflow: hidden;
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
  font-size: 12px;
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
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 600;
  text-align: right;
}
.metrics-value.font-mono {
  font-family: var(--font-mono);
  font-size: 12px;
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
  font-family: var(--font-mono);
  font-size: 12px;
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
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 12px;
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
  .metrics-bar > *:last-child {
    grid-column: span 2;
  }
}
</style>
