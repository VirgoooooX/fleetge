<template>
  <div class="detail-layout">
    <section v-if="host?.metrics" class="metrics-bar">
      <HostMetricsBar label="CPU" :percent="host.metrics.cpuPercent" unit="%" />
      <HostMetricsBar
        label="内存"
        :percent="memPercent"
        :used="host.metrics.memoryUsed"
        :total="host.metrics.memoryTotal"
        unit="GB"
      />
      <HostMetricsBar
        label="磁盘"
        :percent="diskPercent"
        :used="host.metrics.diskUsed"
        :total="host.metrics.diskTotal"
        unit="GB"
      />
      <div class="metrics-item">
        <div class="metrics-header">
          <span class="metrics-label">负载</span>
        </div>
        <div class="metrics-value-container">
          <span class="metrics-value font-mono">{{ loadText }}</span>
        </div>
      </div>
      <div class="metrics-item">
        <div class="metrics-header">
          <span class="metrics-label">运行时间</span>
        </div>
        <div class="metrics-value-container">
          <span class="metrics-value">{{ uptimeText }}</span>
        </div>
      </div>
      <div class="metrics-item">
        <div class="metrics-header">
          <span class="activity-dot" :class="netActivityLevel" />
          <span class="metrics-label">网络</span>
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
          <span class="metrics-label">磁盘 I/O</span>
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
    <el-alert v-else-if="host" title="主机指标不可用" type="warning" show-icon :closable="false" class="metric-warning" />

    <section v-if="host" class="updates-panel">
      <div class="updates-panel__header">
        <div>
          <div class="section-kicker">Image Updates</div>
          <h3 class="section-title">可更新镜像</h3>
        </div>
        <div class="updates-panel__actions">
          <el-tag v-if="displayUpdateCount > 0" type="danger" effect="dark">
            {{ displayUpdateCount }} 个待更新
          </el-tag>
          <el-tag v-else type="success" effect="dark">暂无更新</el-tag>
          <el-button size="small" :loading="updateLoading" @click="runUpdateCheck">
            <el-icon><Refresh /></el-icon>
            重新检查
          </el-button>
        </div>
      </div>

      <div v-if="updatableResults.length > 0" class="update-list">
        <div v-for="item in updatableResults" :key="item.image" class="update-row">
          <div class="update-row__main">
            <code class="image-ref">{{ item.image }}</code>
            <span class="update-row__containers">
              {{ containersByImage[item.image] || 0 }} 个容器使用
            </span>
          </div>
          <div class="update-row__digests">
            <span>local {{ shortDigest(item.current_digest) }}</span>
            <span>registry {{ shortDigest(item.registry_digest) }}</span>
          </div>
          <div class="update-row__actions">
            <UpdateBadge :status="item.status" />
            <el-button
              v-for="stackName in stacksByImage[item.image] || []"
              :key="stackName"
              size="small"
              type="danger"
              plain
              :loading="updatingStack === stackName"
              :disabled="!!updatingStack"
              @click="updateStackFromImage(stackName)"
            >
              更新 {{ stackName }}
            </el-button>
          </div>
        </div>
      </div>

      <el-alert
        v-else-if="displayUpdateCount > 0 && !updateLoading"
        title="更新计数已存在，但当前详情页还没有拿到镜像明细。点击“重新检查”刷新检测结果。"
        type="warning"
        show-icon
        :closable="false"
      />

      <div v-else class="updates-empty">
        当前主机的镜像检查结果没有发现可更新项。
      </div>
    </section>

    <el-tabs v-model="activeTab" class="detail-tabs">
      <el-tab-pane label="Stacks" name="stacks">
        <StackGroup
          v-if="stacks.length > 0"
          :stacks="stacks"
          :host-id="hostId"
          @refresh="fetchDetail"
        />
        <el-empty v-else description="暂无 Stack" />
      </el-tab-pane>
      <el-tab-pane label="容器" name="containers">
        <ContainerTable
          v-if="containers.length > 0"
          :containers="containers"
          :container-stats="containerStats"
          :update-statuses="updateStatuses"
        />
        <el-empty v-else description="暂无容器" />
      </el-tab-pane>
      <el-tab-pane label="Docker Info" name="docker">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="版本">{{ host?.docker_version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="API 版本">{{ host?.api_version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="系统架构">{{ host?.architecture || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Docker Root">{{ host?.docker_root_dir || '-' }}</el-descriptions-item>
          <el-descriptions-item label="镜像数量">{{ host?.image_count ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="运行容器">{{ host?.container_running ?? '-' }}</el-descriptions-item>
        </el-descriptions>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from "vue";
import { useRoute } from "vue-router";
import { Refresh } from "@element-plus/icons-vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { apiClient } from "@/api/client";
import { streamSse } from "@/api/sse";
import { useDashboardStore, type HostSummary } from "@/stores/dashboard";

interface StackService {
  name: string;
  container_id?: string;
  state: string;
  status: string;
}

interface StackSummary {
  name: string;
  status: string;
  compose_file?: string;
  service_count: number;
  running_count: number;
  services: StackService[];
}

interface ContainerPort {
  private_port: number;
  public_port?: number;
  ip?: string;
  type: string;
}

interface ContainerSummary {
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

interface ContainerStats {
  cpu_percent: number;
  memory_usage: number;
  memory_limit: number;
  memory_percent: number;
  network_rx_bytes: number;
  network_tx_bytes: number;
  block_read_bytes: number;
  block_write_bytes: number;
}

interface UpdateResult {
  host_id: string;
  image: string;
  current_digest?: string;
  registry_digest?: string;
  status: string;
}
import HostMetricsBar from "@/components/HostMetricsBar.vue";
import StackGroup from "@/components/StackGroup.vue";
import ContainerTable from "@/components/ContainerTable.vue";
import UpdateBadge from "@/components/UpdateBadge.vue";

const route = useRoute();
const dashboardStore = useDashboardStore();
const hostId = computed(() => route.params.hostId as string);

const loading = ref(true);
const host = ref<HostSummary | null>(null);
const stacks = ref<StackSummary[]>([]);
const containers = ref<ContainerSummary[]>([]);
const containerStats = ref<Record<string, ContainerStats>>({});
const updateResults = ref<UpdateResult[]>([]);
const updateLoading = ref(false);
const updatingStack = ref("");
const activeTab = ref("stacks");

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
  if (d > 0) parts.push(`${d} 天`);
  if (h > 0) parts.push(`${h} 小时`);
  if (m > 0) parts.push(`${m} 分钟`);
  return parts.join(" ") || "刚刚重启";
});

const updatableResults = computed(() => {
  // Deduplicate by image_ref — show one row per image
  const seen = new Set<string>();
  return updateResults.value.filter((item) => {
    if (item.status !== "updatable") return false;
    const key = `${item.host_id}:${item.image}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
});

const displayUpdateCount = computed(() => {
  if (updatableResults.value.length > 0) return updatableResults.value.length;
  return dashboardStore.getHostUpdateCount(hostId.value);
});

const updateStatuses = computed(() => {
  const statuses: Record<string, string> = {};
  for (const item of updateResults.value) {
    statuses[item.image] = item.status;
  }
  return statuses;
});

const containersByImage = computed(() => {
  const counts: Record<string, number> = {};
  for (const container of containers.value) {
    counts[container.image] = (counts[container.image] || 0) + 1;
  }
  return counts;
});

const stacksByImage = computed(() => {
  const stacksByImageRef: Record<string, string[]> = {};
  for (const container of containers.value) {
    if (!container.image || !container.stack_name) continue;
    const existing = stacksByImageRef[container.image] || [];
    if (!existing.includes(container.stack_name)) {
      existing.push(container.stack_name);
    }
    stacksByImageRef[container.image] = existing;
  }
  return stacksByImageRef;
});

function shortDigest(digest?: string): string {
  if (!digest) return "-";
  const normalized = digest.replace(/^sha256:/, "");
  return `sha256:${normalized.slice(0, 12)}`;
}

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

function applyUpdateResults(results: UpdateResult[]) {
  dashboardStore.applyUpdateResults(results || []);
  updateResults.value = (results || []).filter(
    (item) => item.host_id === hostId.value
  );
}

async function fetchUpdateResults() {
  updateLoading.value = true;
  try {
    const res = await apiClient.get("/api/update-checks");
    applyUpdateResults(res.data || []);
  } catch (e) {
    console.error("Failed to fetch update checks:", e);
    updateResults.value = [];
  } finally {
    updateLoading.value = false;
  }
}

async function runUpdateCheck() {
  updateLoading.value = true;
  try {
    const results = await dashboardStore.runUpdateCheck();
    applyUpdateResults(results || []);
    await fetchDetail({ skipUpdates: true });
  } catch (e) {
    console.error("Failed to run update check:", e);
  } finally {
    updateLoading.value = false;
  }
}

async function updateStackFromImage(stackName: string) {
  try {
    await ElMessageBox.confirm(
      `确定要更新 Stack「${stackName}」吗？这会拉取最新镜像并重新创建相关容器。`,
      "更新 Stack",
      {
        confirmButtonText: "更新",
        cancelButtonText: "取消",
        type: "warning",
      }
    );
  } catch {
    return;
  }

  updatingStack.value = stackName;
  try {
    const updateUrl = `/api/hosts/${hostId.value}/stacks/${encodeURIComponent(stackName)}/update`;
    let streamSuccess = false;
    let streamMessage = "";

    await streamSse({
      url: updateUrl,
      method: "POST",
      timeoutMs: 240000,
      onTimeout: () => {
        streamSuccess = false;
        streamMessage = "操作无响应，可能仍在 Dockge 后台执行，请稍后刷新确认。";
      },
      onEvent: (ev) => {
        if (ev.event === "complete") {
          const data = ev.data || {};
          streamSuccess = data.status === "success";
          streamMessage = data.message || "";
        } else if (ev.event === "error") {
          const data = ev.data || {};
          streamSuccess = false;
          streamMessage = data.message || "后端操作失败";
        }
      },
    });

    if (!streamSuccess) {
      throw new Error(streamMessage || "操作失败");
    }

    ElMessage.success(`已触发 ${stackName} 更新`);

    // Force refresh after update — skip stale update check, just fetch fresh data
    await fetchDetail({ skipUpdates: true });

    // Re-run registry digest check
    try {
      const results = await dashboardStore.runUpdateCheck();
      applyUpdateResults(results || []);
    } catch {
      // Update check may fail; use what we have
    }

    // Final refresh with fresh update data
    await fetchDetail({ skipUpdates: true });
  } catch (e: any) {
    const detail = e.response?.data?.detail || e.message;

    // Even on failure, refresh to see actual image state
    try {
      await fetchDetail({ skipUpdates: true });
      const results = await dashboardStore.runUpdateCheck();
      applyUpdateResults(results || []);
    } catch {
      // Best-effort
    }

    ElMessage.error(`更新失败: ${detail}`);
  } finally {
    updatingStack.value = "";
  }
}

async function fetchDetail(options: { skipUpdates?: boolean; silent?: boolean } = {}) {
  if (!options.silent) {
    loading.value = true;
  }
  try {
    const res = await apiClient.post(
      `/api/hosts/${encodeURIComponent(hostId.value)}/refresh`
    );
    host.value = res.data.host || null;
    stacks.value = res.data.stacks || [];
    containers.value = res.data.containers || [];
    containerStats.value = res.data.container_stats || {};

    if (host.value) {
      dashboardStore.upsertHost(host.value);
    }

    if (!options.skipUpdates) {
      await fetchUpdateResults();
    }

  } catch (e: any) {
    console.error("Failed to fetch host detail:", e);
  } finally {
    if (!options.silent) {
      loading.value = false;
    }
  }
}

let pollInterval: any = null;

function startPolling() {
  stopPolling();
  pollInterval = setInterval(() => {
    if (!document.hidden) {
      fetchDetail({ skipUpdates: true, silent: true });
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
  fetchDetail();
  startPolling();
});

watch(hostId, () => {
  fetchDetail();
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
  gap: 16px;
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

/* Telemetry lines styles similar to HostCard.vue */
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

/* Activity dot */
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
.updates-panel {
  border: 1px solid rgba(248, 113, 113, 0.2);
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(127, 29, 29, 0.14), transparent 36%),
    var(--surface-panel);
  padding: 16px;
}
.updates-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}
.updates-panel__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.section-kicker {
  font-size: 11px;
  line-height: 1;
  color: var(--danger);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.section-title {
  margin: 4px 0 0;
  font-size: 16px;
  line-height: 1.2;
  color: var(--text-primary);
}
.update-list {
  display: grid;
  gap: 8px;
}
.update-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(220px, auto) auto;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid rgba(245, 108, 108, 0.22);
  border-radius: 6px;
  background: rgba(127, 29, 29, 0.13);
}
.update-row__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
  flex-wrap: wrap;
}
.update-row__main {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.update-row__containers {
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
}
.update-row__digests {
  display: flex;
  gap: 10px;
  color: var(--text-secondary);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 11px;
  white-space: nowrap;
}
.updates-empty {
  color: var(--text-secondary);
  font-size: 13px;
}
.image-ref {
  font-size: 12px;
  background: var(--code-bg, rgba(5, 9, 20, 0.78));
  padding: 2px 6px;
  border-radius: 4px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
}
.detail-tabs {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--detail-tabs-bg);
  padding: 0 14px 14px;
}

@media (max-width: 900px) {
  .metrics-bar {
    grid-template-columns: 1fr;
  }

  .updates-panel__header,
  .update-row,
  .update-row__main,
  .update-row__digests {
    align-items: flex-start;
    flex-direction: column;
  }
  .update-row {
    display: flex;
  }
  .update-row__digests {
    gap: 4px;
    white-space: normal;
  }
}
</style>
