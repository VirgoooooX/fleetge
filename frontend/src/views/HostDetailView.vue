<template>
  <div class="detail-layout">
    <!-- Back button + header -->
    <header class="detail-header">
      <el-button text @click="$router.push('/')">
        <el-icon><ArrowLeft /></el-icon>
        返回
      </el-button>
      <h2 class="detail-title">{{ host?.display_name || hostId }}</h2>
      <StatusIcon :status="host?.status || 'unknown'" />
      <el-tag v-if="host?.os_info" size="small" type="info">{{ host?.os_info }}</el-tag>
      <el-tag v-if="host?.docker_version" size="small">Docker {{ host?.docker_version }}</el-tag>
    </header>

    <!-- Loading -->
    <div v-if="loading" class="loading-center"><el-icon class="is-loading" :size="32"><Loading /></el-icon></div>

    <!-- Metrics bar -->
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
        <span class="metrics-label">负载</span>
        <span class="metrics-value">{{ loadText }}</span>
      </div>
      <div class="metrics-item">
        <span class="metrics-label">运行时间</span>
        <span class="metrics-value">{{ uptimeText }}</span>
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
          <el-tag v-if="host.update_count > 0" type="danger" effect="dark">
            {{ host.update_count }} 个待更新
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
          <UpdateBadge :status="item.status" />
        </div>
      </div>

      <el-alert
        v-else-if="host.update_count > 0 && !updateLoading"
        title="更新计数已存在，但当前详情页还没有拿到镜像明细。点击“重新检查”刷新检测结果。"
        type="warning"
        show-icon
        :closable="false"
      />

      <div v-else class="updates-empty">
        当前主机的镜像检查结果没有发现可更新项。
      </div>
    </section>

    <!-- Tabs for stacks/containers -->
    <el-tabs v-model="activeTab" class="detail-tabs">
      <el-tab-pane label="Stacks" name="stacks">
        <StackGroup
          v-if="stacks.length > 0"
          :stacks="stacks"
          :host-id="hostId"
          @refresh="fetchDetail"
        />
        <el-empty v-else-if="!loading" description="暂无 Stack" />
      </el-tab-pane>
      <el-tab-pane label="容器" name="containers">
        <ContainerTable
          v-if="containers.length > 0"
          :containers="containers"
          :container-stats="containerStats"
          :update-statuses="updateStatuses"
        />
        <el-empty v-else-if="!loading" description="暂无容器" />
      </el-tab-pane>
    </el-tabs>

    <!-- Docker info card (collapsible) -->
    <el-collapse class="docker-info-collapse">
      <el-collapse-item title="Docker 引擎信息">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="版本">{{ host?.docker_version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="API 版本">{{ host?.api_version || '-' }}</el-descriptions-item>
          <el-descriptions-item label="系统架构">{{ host?.architecture || '-' }}</el-descriptions-item>
          <el-descriptions-item label="Docker Root">{{ host?.docker_root_dir || '-' }}</el-descriptions-item>
          <el-descriptions-item label="镜像数量">{{ host?.image_count ?? '-' }}</el-descriptions-item>
          <el-descriptions-item label="运行容器">{{ host?.container_running ?? '-' }}</el-descriptions-item>
        </el-descriptions>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import { ArrowLeft, Loading, Refresh } from "@element-plus/icons-vue";
import { apiClient } from "@/api/client";
import type { HostSummary } from "@/stores/dashboard";

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
import StatusIcon from "@/components/StatusIcon.vue";
import StackGroup from "@/components/StackGroup.vue";
import ContainerTable from "@/components/ContainerTable.vue";
import UpdateBadge from "@/components/UpdateBadge.vue";

const route = useRoute();
const hostId = computed(() => route.params.hostId as string);

const loading = ref(true);
const host = ref<HostSummary | null>(null);
const stacks = ref<StackSummary[]>([]);
const containers = ref<ContainerSummary[]>([]);
const containerStats = ref<Record<string, ContainerStats>>({});
const updateResults = ref<UpdateResult[]>([]);
const updateLoading = ref(false);
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

const updatableResults = computed(() =>
  updateResults.value.filter((item) => item.status === "updatable")
);

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

function shortDigest(digest?: string): string {
  if (!digest) return "-";
  const normalized = digest.replace(/^sha256:/, "");
  return `sha256:${normalized.slice(0, 12)}`;
}

function applyUpdateResults(results: UpdateResult[]) {
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
    const res = await apiClient.post("/api/update-checks/run");
    applyUpdateResults(res.data.results || []);
    await fetchDetail({ skipUpdates: true });
  } catch (e) {
    console.error("Failed to run update check:", e);
  } finally {
    updateLoading.value = false;
  }
}

async function fetchDetail(options: { skipUpdates?: boolean } = {}) {
  loading.value = true;
  try {
    // Fetch hosts list to get the summary for this host
    const hostsRes = await apiClient.get("/api/hosts");
    host.value =
      (hostsRes.data.hosts || []).find(
        (h: HostSummary) => h.host_id === hostId.value
      ) || null;

    // Fetch stacks
    const stacksRes = await apiClient.get(`/api/hosts/${hostId.value}/stacks`);
    stacks.value = stacksRes.data || [];

    // Fetch containers
    const containersRes = await apiClient.get(
      `/api/hosts/${hostId.value}/containers`
    );
    containers.value = containersRes.data || [];

    // Fetch container stats (running containers only)
    try {
      const statsRes = await apiClient.get(
        `/api/hosts/${hostId.value}/container-stats`
      );
      containerStats.value = statsRes.data || {};
    } catch {
      containerStats.value = {};
    }

    if (!options.skipUpdates) {
      await fetchUpdateResults();
    }

  } catch (e: any) {
    console.error("Failed to fetch host detail:", e);
  } finally {
    loading.value = false;
  }
}

onMounted(fetchDetail);
watch(hostId, () => fetchDetail());
</script>

<style scoped>
.detail-layout {
  min-height: 100vh;
  background: var(--bg-dark);
  padding: 16px 24px;
}
.detail-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.detail-title {
  font-size: 22px;
  font-weight: 700;
  margin: 0;
  color: var(--text-primary);
}
.loading-center {
  display: flex;
  justify-content: center;
  padding: 64px;
}
.metrics-bar {
  display: flex;
  gap: 1px;
  background: var(--bg-card);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 16px;
}
.metrics-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 12px;
  background: var(--bg-card);
}
.metrics-label {
  font-size: 12px;
  color: var(--text-secondary);
}
.metrics-value {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 600;
  margin-top: 2px;
}
.metric-warning {
  margin-bottom: 16px;
}
.updates-panel {
  border: 1px solid var(--border-color);
  border-radius: 8px;
  background: var(--bg-card);
  padding: 14px 16px;
  margin-bottom: 16px;
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
  color: var(--text-secondary);
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
  background: rgba(245, 108, 108, 0.06);
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
  background: var(--bg-dark);
  padding: 2px 6px;
  border-radius: 4px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
}
.detail-tabs {
  margin-bottom: 16px;
}
.docker-info-collapse {
  margin-bottom: 24px;
}

@media (max-width: 900px) {
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
