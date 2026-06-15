<template>
  <section class="host-workspace">
    <aside class="workspace-sidebar">
      <div class="sidebar-compose-row">
        <el-tooltip content="新增 Stack 暂未接入，当前可编辑现有 Compose" placement="top">
          <button class="compose-add-button" type="button" disabled>
            <el-icon><Plus /></el-icon>
            Compose
          </button>
        </el-tooltip>
        <el-tooltip content="重新检查镜像更新" placement="top">
          <el-button
            class="sidebar-icon-button"
            :loading="updateLoading"
            aria-label="重新检查镜像更新"
            @click="$emit('check-updates')"
          >
            <el-icon><Refresh /></el-icon>
          </el-button>
        </el-tooltip>
      </div>

      <div class="sidebar-search">
        <el-icon><Search /></el-icon>
        <input v-model="stackSearch" type="search" placeholder="Search stacks" />
      </div>

      <button
        class="stack-nav-item all"
        :class="{ active: !selectedStackName }"
        type="button"
        @click="showAllStacks"
      >
        <span>All Stacks</span>
        <span class="nav-count">{{ filteredStacks.length }}</span>
      </button>

      <div class="stack-nav-list">
        <button
          v-for="stack in filteredStacks"
          :key="stack.name"
          class="stack-nav-item"
          :class="{ active: selectedStackName === stack.name }"
          type="button"
          @click="selectStack(stack.name)"
        >
          <span
            class="dot-state nav-status-dot"
            :class="`dot-${stackStatusType(stack.status)}`"
            :title="statusLabel(stack.status)"
          />
          <span class="nav-stack-name">{{ stack.name }}</span>
          <UpdateBadge v-if="stackUpdateStatus(stack)" :status="stackUpdateStatus(stack)!" />
        </button>
      </div>
    </aside>

    <main class="workspace-main">
      <div v-if="!selectedStack" class="all-stacks-view">
        <div class="workspace-headline">
          <div>
            <div class="workspace-kicker">Stacks</div>
            <h3>全部 Stacks</h3>
          </div>
          <div class="workspace-summary">
            <span>{{ stacks.length }} stacks</span>
            <span>{{ runningStackCount }} running</span>
          </div>
        </div>

        <div v-if="filteredStacks.length > 0" class="stack-card-list">
          <article
            v-for="stack in filteredStacks"
            :key="stack.name"
            class="dockge-stack-card"
            @click="selectStack(stack.name)"
          >
            <div class="dockge-stack-header">
              <div class="stack-title-row">
                <img v-if="stack.icon_url" :src="stack.icon_url" class="stack-icon-img" @error="onIconError" />
                <el-icon v-else class="stack-title-icon"><FolderOpened /></el-icon>
                <span class="dockge-stack-name">{{ stack.name }}</span>
                <span class="dot-state" :class="`dot-${stackStatusType(stack.status)}`" />
                <span class="stack-state-text">{{ statusLabel(stack.status) }}</span>
                <UpdateBadge v-if="stackUpdateStatus(stack)" :status="stackUpdateStatus(stack)!" />
              </div>
              <div class="stack-card-actions" @click.stop>
                <span class="stack-running-count">
                  {{ stack.running_count }} / {{ stack.service_count }} 运行
                </span>
                <StackActions
                  :host-id="hostId"
                  :stack-name="stack.name"
                  @refresh="$emit('refresh')"
                  @operation-start="onOperationStart(stack.name, $event)"
                  @terminal-line="onTerminalLine(stack.name, $event)"
                  @operation-complete="onOperationComplete(stack.name, $event)"
                />
                <el-tooltip content="编辑 Compose" placement="top">
                  <el-button
                    class="compact-action-button wide"
                    size="small"
                    @click="openCompose(stack.name)"
                  >
                    <el-icon><EditPen /></el-icon>
                    Compose
                  </el-button>
                </el-tooltip>
                <el-tooltip content="查看详情" placement="top">
                  <el-button
                    class="compact-action-button"
                    size="small"
                    aria-label="查看详情"
                    @click="selectStack(stack.name)"
                  >
                    <el-icon><Document /></el-icon>
                  </el-button>
                </el-tooltip>
              </div>
            </div>

            <StackOperationDock
              v-if="isOperationDockVisible(stack.name)"
              class="card-operation-dock"
              :stack-name="stack.name"
              :action="operationPanelAction"
              :lines="terminalOutputs[stack.name] || []"
              :status="operationPanelStatus"
              :message="operationPanelMessage"
              compact
              @close="closeOperationDock"
              @click.stop
            />

            <div v-if="stack.services?.length" class="service-strip">
              <button
                v-for="service in stack.services"
                :key="service.name"
                class="service-strip-row"
                type="button"
                @click.stop="selectServiceContainer(stack.name, service)"
              >
                <StatusIcon :status="service.state === 'running' ? 'online' : 'offline'" />
                <span class="service-name">{{ service.name }}</span>
                <span class="service-status">{{ service.status || service.state }}</span>
                <UpdateBadge
                  v-if="serviceUpdateStatus(stack, service)"
                  :status="serviceUpdateStatus(stack, service)!"
                />
              </button>
            </div>
          </article>
        </div>

        <el-empty v-else description="没有匹配的 Stack" />
      </div>

      <div v-else class="stack-detail-view">
        <header class="detail-hero">
          <div class="detail-title-block">
            <div class="detail-title-row">
              <span class="dot-state detail-status-dot" :class="`dot-${stackStatusType(selectedStack.status)}`" />
              <span class="stack-state-text detail-state-text">{{ statusLabel(selectedStack.status) }}</span>
              <h2>{{ selectedStack.name }}</h2>
              <UpdateBadge
                v-if="stackUpdateStatus(selectedStack)"
                :status="stackUpdateStatus(selectedStack)!"
              />
            </div>
          </div>
          <div class="detail-actions">
            <StackActions
              :host-id="hostId"
              :stack-name="selectedStack.name"
              @refresh="$emit('refresh')"
              @operation-start="onOperationStart(selectedStack.name, $event)"
              @terminal-line="onTerminalLine(selectedStack.name, $event)"
              @operation-complete="onOperationComplete(selectedStack.name, $event)"
            />
            <el-button class="detail-compose-button" @click="openCompose(selectedStack.name)">
              <el-icon><EditPen /></el-icon>
              Compose
            </el-button>
          </div>
        </header>

        <StackOperationDock
          v-if="isOperationDockVisible(selectedStack.name)"
          class="detail-operation-dock"
          :stack-name="selectedStack.name"
          :action="operationPanelAction"
          :lines="terminalOutputs[selectedStack.name] || []"
          :status="operationPanelStatus"
          :message="operationPanelMessage"
          @close="closeOperationDock"
        />

        <div class="stack-detail-grid">
          <div class="detail-left-column">
            <section class="workspace-section">
              <div class="section-heading">
                <h3>容器组</h3>
                <span>{{ selectedStackContainers.length }} containers</span>
              </div>
              <div class="container-group">
                <button
                  v-for="container in selectedStackContainers"
                  :key="container.id"
                  class="container-row"
                  :class="{ active: selectedContainerId === container.id }"
                  type="button"
                  @click="selectContainer(container.id)"
                >
                  <StatusIcon :status="container.state === 'running' ? 'online' : 'offline'" />
                  <div class="container-main">
                    <span class="container-name">{{ container.service_name || container.name }}</span>
                    <span class="container-meta">{{ container.image }}</span>
                  </div>
                  <span class="container-status">{{ container.status || container.state }}</span>
                  <span v-if="formatPorts(container.ports)" class="container-port">
                    {{ formatPorts(container.ports) }}
                  </span>
                  <UpdateBadge
                    v-if="containerUpdateStatus(container)"
                    :status="containerUpdateStatus(container)!"
                  />
                </button>
                <el-empty v-if="selectedStackContainers.length === 0" description="暂无容器" />
              </div>
            </section>

            <section class="workspace-section terminal-section">
              <div class="section-heading">
                <h3>终端</h3>
                <div class="terminal-tools">
                  <el-button size="small" text :loading="logsLoading" @click="loadLogs">
                    <el-icon><Refresh /></el-icon>
                    刷新
                  </el-button>
                </div>
              </div>
              <div class="embedded-terminal" ref="logViewportRef">
                <div v-if="logsLoading && logLines.length === 0" class="terminal-muted">
                  正在加载日志...
                </div>
                <div v-else-if="logLines.length === 0" class="terminal-muted">
                  暂无日志
                </div>
                <div
                  v-for="(line, index) in logLines"
                  :key="`${index}-${line.service}-${line.text}`"
                  class="terminal-log-line"
                  :class="`level-${line.level}`"
                >
                  <span v-if="line.service" class="terminal-service">{{ line.service }}</span>
                  <span class="terminal-message">{{ line.text }}</span>
                </div>
                <div v-if="logsActive" class="terminal-cursor">▊</div>
              </div>
            </section>
          </div>

          <aside class="detail-panel">
            <div class="panel-header">
              <div>
                <div class="workspace-kicker">
                  {{ selectedContainer ? 'Container Detail' : 'Compose Preview' }}
                </div>
                <h3>{{ selectedContainer ? (selectedContainer.service_name || selectedContainer.name) : composeFileName }}</h3>
              </div>
              <el-button
                v-if="selectedContainer"
                size="small"
                text
                @click="selectedContainerId = ''"
              >
                显示 Compose
              </el-button>
            </div>

            <div v-if="selectedContainer" class="container-detail-panel">
              <div class="detail-fields-grid">
                <div class="detail-field">
                  <span>ID</span>
                  <code>{{ selectedContainer.id }}</code>
                </div>
                <div class="detail-field">
                  <span>状态</span>
                  <strong>{{ selectedContainer.status || selectedContainer.state }}</strong>
                </div>
                <div class="detail-field">
                  <span>镜像</span>
                  <code>{{ selectedContainer.image }}</code>
                </div>
                <div class="detail-field">
                  <span>端口</span>
                  <strong>{{ formatPorts(selectedContainer.ports) || '-' }}</strong>
                </div>
              </div>

              <div v-if="selectedContainerStats" class="detail-stats-grid">
                <div>
                  <span>CPU</span>
                  <strong>{{ selectedContainerStats.cpu_percent.toFixed(1) }}%</strong>
                </div>
                <div>
                  <span>Memory</span>
                  <strong>{{ selectedContainerStats.memory_percent.toFixed(1) }}%</strong>
                </div>
                <div>
                  <span>RX</span>
                  <strong>{{ formatBytes(selectedContainerStats.network_rx_bytes) }}</strong>
                </div>
                <div>
                  <span>TX</span>
                  <strong>{{ formatBytes(selectedContainerStats.network_tx_bytes) }}</strong>
                </div>
              </div>

              <div class="detail-section-group">
                <div class="detail-section-title">Runtime</div>
                <div class="detail-fields-grid compact">
                  <div class="detail-field">
                    <span>Restart</span>
                    <strong>{{ formatRestartPolicy(selectedContainer.restart_policy) }}</strong>
                  </div>
                  <div class="detail-field">
                    <span>Restarts</span>
                    <strong>{{ selectedContainer.restart_count ?? 0 }}</strong>
                  </div>
                  <div class="detail-field">
                    <span>Network Mode</span>
                    <strong>{{ selectedContainer.network_mode || '-' }}</strong>
                  </div>
                  <div class="detail-field">
                    <span>Privileged</span>
                    <strong>{{ selectedContainer.privileged ? 'yes' : 'no' }}</strong>
                  </div>
                  <div class="detail-field">
                    <span>User</span>
                    <strong>{{ selectedContainer.user || 'default' }}</strong>
                  </div>
                  <div class="detail-field">
                    <span>Workdir</span>
                    <code>{{ selectedContainer.working_dir || '-' }}</code>
                  </div>
                </div>
              </div>

              <div v-if="formatCommand(selectedContainer.entrypoint) || formatCommand(selectedContainer.command)" class="detail-section-group">
                <div class="detail-section-title">Command</div>
                <div class="detail-list">
                  <span>Entrypoint</span>
                  <code>{{ formatCommand(selectedContainer.entrypoint) || '-' }}</code>
                  <span>Cmd</span>
                  <code>{{ formatCommand(selectedContainer.command) || '-' }}</code>
                </div>
              </div>

              <div v-if="networkEntries.length" class="detail-section-group">
                <div class="detail-section-title">Networks</div>
                <div class="network-detail-list">
                  <div v-for="[name, network] in networkEntries" :key="name" class="network-detail-row">
                    <strong>{{ name }}</strong>
                    <code>{{ network.IPAddress || network.GlobalIPv6Address || '-' }}</code>
                    <span>{{ network.MacAddress || '-' }}</span>
                  </div>
                </div>
              </div>

              <div v-if="visibleMounts.length" class="detail-section-group">
                <div class="detail-section-title">Mounts</div>
                <div class="mount-detail-list">
                  <div v-for="mount in visibleMounts" :key="`${mount.Source}-${mount.Destination}`" class="mount-detail-row">
                    <span class="mount-type">{{ mount.Type || 'mount' }}</span>
                    <code>{{ mount.Source || mount.Name || '-' }}</code>
                    <span>-&gt;</span>
                    <code>{{ mount.Destination || '-' }}</code>
                    <span>{{ mount.RW === false ? 'ro' : 'rw' }}</span>
                  </div>
                </div>
              </div>

              <div v-if="selectedContainer.repo_digests?.length" class="detail-list">
                <span>Repo Digests</span>
                <code v-for="digest in selectedContainer.repo_digests" :key="digest">
                  {{ digest }}
                </code>
              </div>

              <div v-if="visibleContainerLabels.length" class="detail-list labels">
                <span>Labels</span>
                <code
                  v-for="[key, value] in visibleContainerLabels"
                  :key="key"
                >
                  {{ key }}={{ value }}
                </code>
              </div>
            </div>

            <div v-else class="compose-preview">
              <div v-if="composeLoading" class="panel-muted">正在加载 compose.yaml...</div>
              <el-alert
                v-else-if="composeError"
                :title="composeError"
                type="warning"
                show-icon
                :closable="false"
              />
              <pre v-else><code>{{ composeYaml || 'Dockge 没有返回 compose.yaml。' }}</code></pre>
            </div>
          </aside>
        </div>
      </div>
    </main>

    <ComposeDrawer
      v-if="composeDrawerVisible"
      :visible="composeDrawerVisible"
      :host-id="hostId"
      :stack-name="currentComposeStack"
      @close="composeDrawerVisible = false"
      @saved="$emit('refresh')"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, reactive, ref, watch } from "vue";
import {
  Document,
  EditPen,
  FolderOpened,
  Plus,
  Refresh,
  Search,
} from "@element-plus/icons-vue";
import { apiClient } from "@/api/client";
import { streamSse } from "@/api/sse";
import StatusIcon from "./StatusIcon.vue";
import StackActions from "./StackActions.vue";
import type { OperationState, TerminalLineEvent } from "./StackActions.vue";
import StackOperationDock from "./StackOperationDock.vue";
import ComposeDrawer from "./ComposeDrawer.vue";
import UpdateBadge from "./UpdateBadge.vue";

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
  icon_url?: string;  // 自定义图标（网络 URL 或 /api/static/icons/...）
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
  image_id?: string;
  repo_digests?: string[];
  state: string;
  status: string;
  created: number;
  ports: ContainerPort[];
  labels?: Record<string, string>;
  stack_name?: string;
  service_name?: string;
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

export interface ContainerStatsData {
  cpu_percent: number;
  memory_usage: number;
  memory_limit: number;
  memory_percent: number;
  network_rx_bytes: number;
  network_tx_bytes: number;
  block_read_bytes: number;
  block_write_bytes: number;
}

interface StackLogLine {
  service: string;
  text: string;
  level: "info" | "warn" | "error";
}

const props = defineProps<{
  hostId: string;
  stacks: StackSummary[];
  containers: ContainerSummary[];
  containerStats: Record<string, ContainerStatsData>;
  updateStatuses: Record<string, string>;
  updateLoading?: boolean;
}>();

defineEmits<{
  refresh: [];
  "check-updates": [];
}>();

const stackSearch = ref("");
const selectedStackName = ref("");
const selectedContainerId = ref("");

const composeYaml = ref("");
const composeFileName = ref("compose.yaml");
const composeLoading = ref(false);
const composeError = ref("");

const logLines = ref<StackLogLine[]>([]);
const logsLoading = ref(false);
const logsActive = ref(false);
const logViewportRef = ref<HTMLElement | null>(null);
let logStreamController: AbortController | null = null;

const terminalOutputs = reactive<Record<string, string[]>>({});
const operationPanelVisible = ref(false);
const operationPanelStack = ref("");
const operationPanelStatus = ref<"running" | "success" | "error" | "idle">("idle");
const operationPanelMessage = ref("");
const operationPanelAction = ref("");
let operationAutoCloseTimer: ReturnType<typeof setTimeout> | null = null;

const composeDrawerVisible = ref(false);
const currentComposeStack = ref("");

const filteredStacks = computed(() => {
  const query = stackSearch.value.trim().toLowerCase();
  if (!query) return props.stacks;
  return props.stacks.filter((stack) => stack.name.toLowerCase().includes(query));
});

const selectedStack = computed(() =>
  props.stacks.find((stack) => stack.name === selectedStackName.value) || null
);

const selectedStackContainers = computed(() => {
  if (!selectedStack.value) return [];
  return props.containers
    .filter((container) => container.stack_name === selectedStack.value?.name)
    .sort((a, b) => (a.service_name || a.name).localeCompare(b.service_name || b.name));
});

const selectedContainer = computed(() =>
  selectedStackContainers.value.find((container) => container.id === selectedContainerId.value) || null
);

const selectedContainerStats = computed(() =>
  selectedContainer.value ? props.containerStats[selectedContainer.value.id] : null
);

const visibleContainerLabels = computed(() => {
  const labels = selectedContainer.value?.labels || {};
  return Object.entries(labels)
    .filter(([key]) => !isInternalDockerLabel(key))
    .sort(([a], [b]) => a.localeCompare(b));
});

const networkEntries = computed(() =>
  Object.entries(selectedContainer.value?.networks || {})
    .sort(([a], [b]) => a.localeCompare(b))
);

const visibleMounts = computed(() =>
  (selectedContainer.value?.mounts || [])
    .filter((mount) => mount.Destination || mount.Source || mount.Name)
    .sort((a, b) => String(a.Destination || "").localeCompare(String(b.Destination || "")))
);

const runningStackCount = computed(() =>
  props.stacks.filter((stack) => stack.status === "running").length
);

function statusLabel(status: string): string {
  if (status === "running") return "已启动";
  if (status === "stopped") return "已停止";
  if (status === "partially running") return "部分运行";
  return status || "未知";
}

function stackStatusType(status: string): string {
  if (status === "running") return "running";
  if (status === "stopped") return "stopped";
  return "partial";
}

function onIconError(event: Event) {
  // Hide broken <img> so the fallback <el-icon> shows through
  const img = event.target as HTMLImageElement;
  if (img) {
    img.style.display = "none";
  }
}

function containerUpdateStatus(container: ContainerSummary): string | null {
  const status = props.updateStatuses[container.image];
  return status && status !== "up_to_date" && status !== "needs_auth" ? status : null;
}

function isInternalDockerLabel(key: string): boolean {
  return key.startsWith("com.docker.compose.") ||
    key.startsWith("org.opencontainers.image.") ||
    key === "desktop.docker.io/wsl-distro";
}

function stackUpdateStatus(stack: StackSummary): string | null {
  const statuses = props.containers
    .filter((container) => container.stack_name === stack.name)
    .map((container) => containerUpdateStatus(container))
    .filter((status): status is string => Boolean(status));

  if (statuses.includes("updatable")) return "updatable";
  if (statuses.includes("check_failed")) return "check_failed";
  return null;
}

function containerForService(stack: StackSummary, service: StackService): ContainerSummary | null {
  return props.containers.find((container) => {
    if (service.container_id && container.id.startsWith(service.container_id)) return true;
    return container.stack_name === stack.name &&
      (container.service_name === service.name || container.name === service.name);
  }) || null;
}

function serviceUpdateStatus(stack: StackSummary, service: StackService): string | null {
  const container = containerForService(stack, service);
  return container ? containerUpdateStatus(container) : null;
}

function formatPorts(ports: ContainerPort[] = []): string {
  return ports
    .map((port) => port.public_port
      ? `${port.public_port}:${port.private_port}/${port.type}`
      : `${port.private_port}/${port.type}`)
    .join(", ");
}

function formatCommand(value: string[] | string | null | undefined): string {
  if (!value) return "";
  if (Array.isArray(value)) {
    return value.filter(Boolean).join(" ");
  }
  return value;
}

function formatRestartPolicy(policy?: Record<string, any>): string {
  if (!policy) return "-";
  const name = policy.Name || policy.name || "";
  const retryCount = policy.MaximumRetryCount ?? policy.maximum_retry_count;
  if (!name) return "-";
  return retryCount ? `${name} (${retryCount})` : name;
}

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index++;
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} ${units[index]}`;
}

function showAllStacks() {
  selectedStackName.value = "";
  selectedContainerId.value = "";
  stopLogs();
}

function selectStack(stackName: string) {
  selectedStackName.value = stackName;
  selectedContainerId.value = "";
}

function selectContainer(containerId: string) {
  selectedContainerId.value = containerId;
}

function selectServiceContainer(stackName: string, service: StackService) {
  selectStack(stackName);
  const stack = props.stacks.find((item) => item.name === stackName);
  if (!stack) return;
  const container = containerForService(stack, service);
  if (container) {
    selectedContainerId.value = container.id;
  }
}

function openCompose(stackName: string) {
  currentComposeStack.value = stackName;
  composeDrawerVisible.value = true;
}

function isOperationDockVisible(stackName: string): boolean {
  return operationPanelVisible.value && operationPanelStack.value === stackName;
}

function closeOperationDock() {
  clearOperationAutoClose();
  operationPanelVisible.value = false;
}

function clearOperationAutoClose() {
  if (operationAutoCloseTimer) {
    clearTimeout(operationAutoCloseTimer);
    operationAutoCloseTimer = null;
  }
}

function scheduleOperationAutoClose(stackName: string, delayMs: number) {
  clearOperationAutoClose();
  operationAutoCloseTimer = setTimeout(() => {
    if (operationPanelStack.value === stackName && operationPanelStatus.value !== "running") {
      operationPanelVisible.value = false;
    }
  }, delayMs);
}

async function loadCompose() {
  if (!selectedStack.value) return;
  composeLoading.value = true;
  composeError.value = "";
  composeYaml.value = "";
  composeFileName.value = "compose.yaml";
  try {
    const res = await apiClient.get(
      `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(selectedStack.value.name)}/compose`
    );
    composeYaml.value = res.data.compose_yaml || "";
    composeFileName.value = res.data.compose_file_name || "compose.yaml";
  } catch (error: any) {
    composeError.value = error.response?.data?.detail || error.message || "Compose 加载失败";
  } finally {
    composeLoading.value = false;
  }
}

function appendLogLine(text: string, service = "", level: StackLogLine["level"] = "info") {
  const cleanText = normalizeLogText(text);
  if (!cleanText && !service) return;
  logLines.value.push({ service, text: cleanText, level });
  if (logLines.value.length > 500) {
    logLines.value = logLines.value.slice(-500);
  }
  nextTick(() => {
    if (logViewportRef.value) {
      logViewportRef.value.scrollTop = logViewportRef.value.scrollHeight;
    }
  });
}

function normalizeLogText(text: string): string {
  return text.replace(/\t/g, "  ").trimEnd();
}

function stopLogs() {
  if (logStreamController) {
    logStreamController.abort();
    logStreamController = null;
  }
  logsActive.value = false;
  logsLoading.value = false;
}

function loadLogs() {
  if (!selectedStack.value) return;
  stopLogs();
  logsLoading.value = true;
  logsActive.value = true;
  logLines.value = [];

  const controller = new AbortController();
  logStreamController = controller;
  const stackName = selectedStack.value.name;
  const url =
    `/api/hosts/${encodeURIComponent(props.hostId)}` +
    `/stacks/${encodeURIComponent(stackName)}` +
    "/logs/stream?tail=120";

  void streamSse({
    url,
    signal: controller.signal,
    onEvent: (ev) => {
      if (ev.event === "ready") {
        logsLoading.value = false;
        return;
      }
      if (ev.event === "line") {
        logsLoading.value = false;
        const service = ev.data?.service;
        const text = ev.data?.text ?? "";
        appendLogLine(text, service || "", logLevel(text));
        return;
      }
      if (ev.event === "error") {
        logsLoading.value = false;
        appendLogLine(ev.data?.message || "log stream failed", ev.data?.service || "", "error");
        return;
      }
      if (ev.event === "complete") {
        logsLoading.value = false;
        logsActive.value = false;
        appendLogLine(ev.data?.message || "Log stream ended.", "", "warn");
      }
    },
  }).catch((error: any) => {
    if (controller.signal.aborted) return;
    appendLogLine(`Failed to stream logs: ${error.message}`, "", "error");
  }).finally(() => {
    if (logStreamController === controller) {
      logStreamController = null;
    }
    logsLoading.value = false;
    logsActive.value = false;
  });
}

function logLevel(text: string): StackLogLine["level"] {
  if (/\b(error|fatal|exception|traceback|failed)\b/i.test(text)) return "error";
  if (/\b(warn|warning|deprecated|retry)\b/i.test(text)) return "warn";
  return "info";
}

function onTerminalLine(stackName: string, payload: TerminalLineEvent) {
  if (!terminalOutputs[stackName]) {
    terminalOutputs[stackName] = [];
  }
  terminalOutputs[stackName].push(payload.line);

  if (!operationPanelVisible.value || operationPanelStack.value !== stackName) {
    operationPanelStack.value = stackName;
    operationPanelStatus.value = "running";
    operationPanelAction.value = payload.action;
    operationPanelVisible.value = true;
  }
}

function onOperationStart(stackName: string, state: OperationState) {
  clearOperationAutoClose();
  terminalOutputs[stackName] = [];
  operationPanelStack.value = stackName;
  operationPanelStatus.value = "running";
  operationPanelMessage.value = state.message;
  operationPanelAction.value = state.action;
  operationPanelVisible.value = true;
}

function onOperationComplete(stackName: string, state: OperationState) {
  operationPanelStatus.value = state.status === "success"
    ? "success"
    : state.status === "error"
      ? "error"
      : "idle";
  operationPanelMessage.value = state.message;
  operationPanelAction.value = state.action;
  scheduleOperationAutoClose(stackName, state.status === "success" ? 2400 : 6500);
}

watch(selectedStackName, () => {
  if (!selectedStack.value) {
    composeYaml.value = "";
    selectedContainerId.value = "";
    stopLogs();
    return;
  }
  selectedContainerId.value = "";
  void loadCompose();
  loadLogs();
});

watch(
  () => props.stacks,
  () => {
    if (selectedStackName.value && !selectedStack.value) {
      showAllStacks();
    }
  }
);

onUnmounted(() => {
  clearOperationAutoClose();
  stopLogs();
});
</script>

<style scoped>
.host-workspace {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 16px;
  height: 100%;
  min-height: 0;
  flex: 1;
}

.workspace-sidebar,
.workspace-main {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel);
  min-height: 0;
}

.workspace-sidebar {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px;
  min-width: 0;
}

.sidebar-compose-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.compose-add-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 34px;
  padding: 0 14px;
  border: 0;
  border-radius: 999px;
  background: linear-gradient(135deg, #63c7ff, #7be7c8);
  color: #03111f;
  font-size: 13px;
  font-weight: 700;
  cursor: not-allowed;
  opacity: 0.7;
}

.sidebar-icon-button,
.compact-action-button,
.detail-compose-button {
  border-color: var(--border-subtle) !important;
  background: var(--stack-action-bg, rgba(148, 163, 184, 0.08)) !important;
  color: var(--text-secondary) !important;
}

.sidebar-icon-button {
  width: 34px;
  height: 34px;
  padding: 0 !important;
}

.sidebar-search {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  padding: 0 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-base);
  color: var(--text-secondary);
}

.sidebar-search input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text-primary);
  font-size: 13px;
}

.stack-nav-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow: auto;
}

.stack-nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 40px;
  padding: 7px 9px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}

.stack-nav-item:hover,
.stack-nav-item.active {
  border-color: var(--border-subtle);
  background: var(--surface-muted);
}

.stack-nav-item.all {
  justify-content: space-between;
  color: var(--text-secondary);
}

.nav-stack-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  font-weight: 650;
}

.nav-status-dot {
  flex: 0 0 auto;
}

.nav-count {
  font-family: var(--font-mono);
  color: var(--text-muted);
}

.workspace-main {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 16px;
  overflow-x: hidden;
  overflow-y: auto;
}

.stack-detail-view {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 100%;
}

.workspace-headline,
.detail-hero,
.dockge-stack-header,
.section-heading,
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.workspace-kicker {
  color: var(--accent-blue);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.workspace-headline h3,
.section-heading h3,
.panel-header h3 {
  margin: 3px 0 0;
  color: var(--text-primary);
}

.workspace-summary,
.section-heading span {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--text-secondary);
  font-size: 12px;
}

.stack-card-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
}

.dockge-stack-card,
.workspace-section,
.detail-panel {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-base);
}

.dockge-stack-card {
  padding: 16px;
  cursor: pointer;
}

.dockge-stack-card:hover {
  border-color: var(--border-strong);
}

.stack-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.stack-icon-img {
  width: 20px;
  height: 20px;
  border-radius: 4px;
  object-fit: contain;
  flex-shrink: 0;
}

.stack-title-icon {
  flex-shrink: 0;
}

.dockge-stack-name {
  overflow: hidden;
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stack-state-text {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}

.stack-card-actions,
.detail-actions,
.terminal-tools {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.stack-running-count {
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.compact-action-button {
  height: 28px;
  min-height: 28px;
  padding: 0 8px !important;
  border-radius: 7px !important;
}

.compact-action-button:not(.wide) {
  width: 28px;
  padding: 0 !important;
}

.service-strip,
.container-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
}

.service-strip-row,
.container-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 34px;
  border: 0;
  border-radius: 7px;
  background: var(--stack-service-bg, rgba(148, 163, 184, 0.08));
  color: var(--text-primary);
  text-align: left;
  cursor: pointer;
}

.service-strip-row {
  padding: 0 10px;
}

.service-strip-row:hover,
.container-row:hover,
.container-row.active {
  background: var(--stack-service-hover-bg, rgba(96, 165, 250, 0.12));
}

.service-name,
.container-name {
  color: var(--text-primary);
  font-weight: 650;
}

.service-status,
.container-status,
.container-port,
.container-meta {
  color: var(--text-secondary);
  font-size: 12px;
}

.service-status {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  min-height: 20px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.status-pill.large {
  min-height: 30px;
  padding: 0 14px;
  font-size: 16px;
}

.status-running {
  background: rgba(74, 222, 128, 0.16);
  color: var(--success);
}

.status-stopped {
  background: rgba(148, 163, 184, 0.14);
  color: var(--text-secondary);
}

.status-partial {
  background: rgba(245, 158, 11, 0.15);
  color: var(--warning);
}

.dot-state {
  width: 9px;
  height: 9px;
  border-radius: 50%;
}

.dot-running {
  background: var(--success);
  box-shadow: 0 0 7px var(--success);
}

.dot-stopped {
  background: var(--text-muted);
}

.dot-partial {
  background: var(--warning);
}

.detail-hero {
  align-items: flex-start;
  margin-bottom: 12px;
}

.detail-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.detail-title-row h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: 28px;
}

.detail-status-dot {
  width: 12px;
  height: 12px;
}

.detail-state-text {
  padding-right: 4px;
  font-size: 14px;
}

.detail-compose-button {
  height: 32px;
  border-radius: 8px !important;
  font-weight: 700;
}

.stack-detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(260px, 0.7fr);
  gap: 16px;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.card-operation-dock {
  margin-top: 12px;
}

.detail-operation-dock {
  margin-bottom: 14px;
}

.detail-left-column {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  min-height: 0;
}

.workspace-section,
.detail-panel {
  padding: 16px;
  min-width: 0;
}

.detail-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.container-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) minmax(70px, auto) minmax(90px, auto) auto;
  padding: 8px 10px;
}

.container-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.container-name,
.container-meta,
.container-status,
.container-port {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.terminal-section {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  border: 0;
  background: transparent;
  padding: 0;
}

.embedded-terminal {
  flex: 1;
  min-height: 0;
  margin-top: 12px;
  overflow: auto;
  border-radius: 8px;
  background: #020609;
  color: #e5f2ff;
  font-family: "Cascadia Code", "Fira Code", "JetBrains Mono", ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.45;
  padding: 10px;
}

:global([data-theme="light"] .embedded-terminal) {
  border: 1px solid rgba(60, 72, 88, 0.16);
  background: #f8fafc;
  color: #0f172a;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.72);
}

.terminal-log-line {
  display: grid;
  grid-template-columns: minmax(76px, max-content) minmax(0, 1fr);
  align-items: baseline;
  gap: 10px;
  padding: 2px 4px;
  border-radius: 5px;
  white-space: pre-wrap;
}

.terminal-log-line + .terminal-log-line {
  margin-top: 1px;
}

.terminal-log-line.level-error {
  background: rgba(248, 113, 113, 0.08);
  color: #fecaca;
}

.terminal-log-line.level-warn {
  background: rgba(251, 191, 36, 0.08);
  color: #fde68a;
}

.terminal-service {
  overflow: hidden;
  max-width: 15ch;
  border-right: 1px solid rgba(148, 163, 184, 0.20);
  color: #38bdf8;
  font-weight: 800;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.terminal-message {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.terminal-muted {
  color: #8aa0b7;
}

:global([data-theme="light"] .terminal-muted) {
  color: #64748b;
}

:global([data-theme="light"] .terminal-log-line.level-error) {
  background: rgba(220, 38, 38, 0.07);
  color: #991b1b;
}

:global([data-theme="light"] .terminal-log-line.level-warn) {
  background: rgba(217, 119, 6, 0.08);
  color: #92400e;
}

:global([data-theme="light"] .terminal-service) {
  border-right-color: rgba(60, 72, 88, 0.16);
  color: #2563eb;
}

.terminal-cursor {
  display: inline-block;
  color: #ffffff;
  animation: blink 1s step-end infinite;
}

:global([data-theme="light"] .terminal-cursor) {
  color: #0f172a;
}

.panel-header {
  flex: 0 0 auto;
  margin-bottom: 12px;
}

.compose-preview {
  display: flex;
  flex: 1;
  min-height: 0;
}

.compose-preview pre {
  flex: 1;
  min-height: 0;
  max-height: none;
  width: 100%;
  margin: 0;
  overflow-x: hidden;
  overflow-y: auto;
  border-radius: 8px;
  background: var(--surface-base);
  color: var(--text-primary);
  font-family: "Cascadia Code", "Fira Code", "JetBrains Mono", ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.55;
  padding: 14px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.panel-muted {
  color: var(--text-secondary);
  font-size: 13px;
}

.container-detail-panel {
  display: flex;
  flex-direction: column;
  flex: 1;
  gap: 10px;
  min-height: 0;
  overflow: auto;
}

.detail-fields-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.detail-fields-grid.compact {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.detail-field,
.detail-list {
  display: grid;
  gap: 6px;
  padding: 10px;
  border-radius: 8px;
  background: var(--surface-base);
}

.detail-field span,
.detail-list > span,
.detail-stats-grid span {
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

.detail-field code,
.detail-list code {
  overflow: hidden;
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 12px;
  text-overflow: ellipsis;
}

.detail-section-group {
  display: grid;
  gap: 8px;
}

.detail-section-title {
  color: var(--accent-blue);
  font-size: 11px;
  font-weight: 850;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.detail-stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.detail-stats-grid > div {
  display: grid;
  gap: 5px;
  padding: 10px;
  border-radius: 8px;
  background: var(--surface-base);
}

.detail-stats-grid strong,
.detail-field strong {
  color: var(--text-primary);
  font-size: 13px;
}

.detail-list.labels {
  max-height: 240px;
  overflow: auto;
}

.network-detail-list,
.mount-detail-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.network-detail-row,
.mount-detail-row {
  align-items: center;
  min-width: 0;
  padding: 9px 10px;
  border-radius: 8px;
  background: var(--surface-base);
  color: var(--text-secondary);
  font-size: 12px;
}

.network-detail-row {
  display: grid;
  grid-template-columns: minmax(80px, 0.7fr) minmax(0, 1fr) minmax(90px, 0.8fr);
  gap: 8px;
}

.mount-detail-row {
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto minmax(0, 1fr) 34px;
  gap: 8px;
}

.network-detail-row strong {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.network-detail-row code,
.mount-detail-row code {
  min-width: 0;
  overflow: hidden;
  color: var(--text-primary);
  font-family: var(--font-mono);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mount-type {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  height: 20px;
  border-radius: 999px;
  background: rgba(96, 165, 250, 0.12);
  color: var(--accent-blue);
  font-size: 11px;
  font-weight: 800;
  text-transform: lowercase;
}

@keyframes blink {
  50% { opacity: 0; }
}

@media (max-width: 1100px) {
  .host-workspace {
    grid-template-columns: 1fr;
  }

  .workspace-sidebar {
    max-height: none;
  }

  .stack-nav-list {
    max-height: 260px;
  }

  .stack-detail-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .workspace-main,
  .workspace-sidebar,
  .dockge-stack-card,
  .workspace-section,
  .detail-panel {
    padding: 12px;
  }

  .dockge-stack-header,
  .detail-hero,
  .workspace-headline {
    align-items: flex-start;
    flex-direction: column;
  }

  .stack-card-actions,
  .detail-actions {
    justify-content: flex-start;
  }

  .container-row {
    grid-template-columns: auto minmax(0, 1fr);
  }

  .container-status,
  .container-port {
    grid-column: 2;
  }

  .detail-stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
