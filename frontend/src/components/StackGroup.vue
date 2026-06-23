<template>
  <div class="stack-list">
    <el-card
      v-for="stack in sortedStacks"
      :key="stack.name"
      class="stack-card"
      :class="{ 'is-stopped': stack.status === 'stopped' || stack.status === 'inactive' || stack.status === 'exited' }"
      shadow="never"
    >
      <div class="stack-header">
        <div class="stack-header-left">
          <el-icon v-if="!stack.icon_url" :size="18">
            <FolderOpened />
          </el-icon>
          <img v-else :src="stack.icon_url" class="stack-icon-img" @error="onIconError" />
          <span class="stack-name">{{ stack.name }}</span>
          <StatusIcon :status="stackStatusType(stack.status)" />
          <el-tag :type="stackTagType(stack.status)" size="small">
            {{ statusLabel(stack.status) }}
          </el-tag>
        </div>
        <div class="stack-header-right">
          <span class="stack-service-count">
            {{ t('stackGroup.running', { running: stack.running_count, total: stack.service_count }) }}
          </span>
          <StackActions
            :host-id="hostId"
            :stack-name="stack.name"
            show-compose
            show-logs
            @refresh="$emit('refresh')"
            @operation-start="onOperationStart"
            @terminal-chunk="onTerminalChunk"
            @operation-complete="onOperationComplete"
            @compose="openCompose(stack.name)"
            @logs="openLogs(stack.name)"
          />
        </div>
      </div>

      <!-- Operation status line -->
      <div
        v-if="operationStates[stack.name]"
        class="stack-operation-status"
        :class="`op-${operationStates[stack.name].status}`"
      >
        <el-icon v-if="operationStates[stack.name].status === 'running'" class="is-loading">
          <Loading />
        </el-icon>
        <el-icon v-else-if="operationStates[stack.name].status === 'success'">
          <SuccessFilled />
        </el-icon>
        <el-icon v-else-if="operationStates[stack.name].status === 'error'">
          <WarningFilled />
        </el-icon>
        <el-icon v-else-if="operationStates[stack.name].status === 'timeout'">
          <Clock />
        </el-icon>
        <span class="op-message">{{ operationStates[stack.name].message }}</span>
        <el-button
          v-if="operationStates[stack.name].logTail"
          text
          size="small"
          type="warning"
          @click="showLogTail(stack.name)"
        >
          {{ t('stackGroup.viewOutput') }}
        </el-button>
      </div>

      <!-- Services -->
      <div v-if="stack.services && stack.services.length > 0" class="stack-services">
        <div
          v-for="svc in stack.services"
          :key="svc.name"
          class="service-row"
        >
          <StatusIcon :status="svc.state === 'running' ? 'online' : 'offline'" />
          <span class="service-name">{{ svc.name }}</span>
          <span class="service-status">{{ svc.status }}</span>
        </div>
      </div>
    </el-card>
  </div>

  <!-- Terminal output drawer (live streaming) -->
  <TerminalDrawer
    :visible="terminalDrawerVisible"
    :stack-name="terminalDrawerStack"
    :lines="(terminalDrawerStack ? terminalOutputs[terminalDrawerStack] : []) || []"
    :status="terminalDrawerStatus"
    :message="terminalDrawerMessage"
    @close="terminalDrawerVisible = false"
  />

  <!-- Legacy log-tail dialog (non-streaming fallback) -->
  <el-dialog
    v-model="logTailVisible"
        :title="t('stackGroup.terminalTitle', { name: currentTailStack })"
    width="80%"
  >
    <pre class="log-tail-content">{{ currentTailContent }}</pre>
  </el-dialog>

  <!-- Log drawer -->
  <LogDrawer
    v-if="logDrawerVisible"
    :visible="logDrawerVisible"
    :host-id="hostId"
    :stack-name="currentLogStack"
    @close="logDrawerVisible = false"
  />

  <ComposeDrawer
    v-if="composeDrawerVisible"
    :visible="composeDrawerVisible"
    :host-id="hostId"
    :stack-name="currentComposeStack"
    @close="composeDrawerVisible = false"
    @saved="$emit('refresh')"
    @deploy="handleComposeDeploy"
  />
</template>

<script setup lang="ts">
import { ref, reactive, computed } from "vue";
import { useI18n } from "vue-i18n";
import { FolderOpened, Document, EditPen, Loading, SuccessFilled, WarningFilled, Clock } from "@element-plus/icons-vue";
import StatusIcon from "./StatusIcon.vue";
import StackActions from "./StackActions.vue";
import type { OperationState, TerminalChunkEvent } from "./StackActions.vue";
import LogDrawer from "./LogDrawer.vue";
import ComposeDrawer, { type ComposeDeployPayload } from "./ComposeDrawer.vue";
import TerminalDrawer from "./TerminalDrawer.vue";
import { streamSse } from "@/api/sse";
import { ElMessage } from "element-plus";
import { sortStacks } from "@/utils/stackSorting";

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
  icon_url?: string;  // 自定义图标
  management_status?: string;
}

const props = defineProps<{
  stacks: StackSummary[];
  hostId: string;
}>();

const emit = defineEmits<{ refresh: [] }>();

const sortedStacks = computed(() => sortStacks(props.stacks));

const { t } = useI18n();

// ── Terminal / streaming state ──────────────────────────────────

const terminalOutputs = reactive<Record<string, string[]>>({});
const terminalDrawerVisible = ref(false);
const terminalDrawerStack = ref("");
const terminalDrawerStatus = ref<"running" | "success" | "error" | "idle">("idle");
const terminalDrawerMessage = ref("");

function onTerminalChunk(stackName: string, payload: TerminalChunkEvent) {
  if (!terminalOutputs[stackName]) {
    terminalOutputs[stackName] = [];
  }
  terminalOutputs[stackName].push(payload.chunk);

  // Open drawer on first line if not already open for this stack
  if (!terminalDrawerVisible.value || terminalDrawerStack.value !== stackName) {
    terminalDrawerStack.value = stackName;
    terminalDrawerStatus.value = "running";
    terminalDrawerVisible.value = true;
  }
}

function onOperationStart(stackName: string, state: OperationState) {
  operationStates[stackName] = state;
  // Clear previous terminal output for this stack
  terminalOutputs[stackName] = [];
  terminalDrawerStack.value = stackName;
  terminalDrawerStatus.value = "running";
  terminalDrawerMessage.value = state.message;
}

function onOperationComplete(stackName: string, state: OperationState) {
  operationStates[stackName] = state;

  const mappedStatus = state.status === "success"
    ? "success" as const
    : state.status === "error"
      ? "error" as const
      : "idle" as const;

  terminalDrawerStatus.value = mappedStatus;
  terminalDrawerMessage.value = state.message;

  // Auto-close terminal on success after a short delay
  if (state.status === "success") {
    setTimeout(() => {
      // Only close if no new operation started
      if (terminalDrawerStack.value === stackName && terminalDrawerStatus.value === "success") {
        terminalDrawerVisible.value = false;
      }
    }, 5000);
  }

  // Auto-clear success status line after 8 seconds
  if (state.status === "success") {
    setTimeout(() => {
      if (operationStates[stackName]?.status === "success") {
        delete operationStates[stackName];
      }
    }, 8000);
  }
}

async function handleComposeDeploy(payload: ComposeDeployPayload) {
  const stackName = payload.stackName;
  const action = "deploy";
  const label = t("stackOp.deploying");
  const startedAt = Date.now();
  const controller = new AbortController();

  const runningState: OperationState = {
    action,
    status: "running",
    message: t("stack.confirm.running", { action: label }),
    updatedAt: startedAt,
    abort: () => controller.abort(),
  };

  onOperationStart(stackName, runningState);

  let completed = false;

  try {
    const cols = 110;
    const rows = 24;
    const url = `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(stackName)}/compose/deploy?cols=${cols}&rows=${rows}`;

    await streamSse({
      url,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      timeoutMs: 300000,
      signal: controller.signal,
      body: JSON.stringify({
        compose_yaml: payload.composeYaml,
        compose_env: payload.composeEnv,
        compose_file_name: payload.composeFileName,
        is_add: payload.isAdd,
      }),
      onTimeout: () => {
        if (completed) return;
        completed = true;
        onOperationComplete(stackName, {
          action,
          status: "timeout",
          message: t("compose.deployTimeout"),
          updatedAt: Date.now(),
        });
      },
      onEvent: (ev) => {
        if (ev.event === "chunk") {
          onTerminalChunk(stackName, { action, chunk: ev.data?.raw ?? ev.rawData });
        } else if (ev.event === "line") {
          onTerminalChunk(stackName, { action, chunk: ev.data?.text ?? ev.rawData });
        } else if (ev.event === "complete") {
          completed = true;
          const data = ev.data || {};
          const success = data.status === "success";

          onOperationComplete(stackName, {
            action,
            status: success ? "success" : "error",
            message: data.message || (success ? t("compose.deploySuccess") : t("compose.deployFailed", { detail: "" })),
            updatedAt: Date.now(),
          });

          if (success) {
            ElMessage.success(payload.isAdd ? t("compose.createdAndDeployed") : t("compose.deployedAndSaved"));
            emit("refresh");
          } else {
            ElMessage.error(t("compose.deployFailed", { detail: data.message || t("compose.unknownError") }));
          }
        } else if (ev.event === "error") {
          completed = true;
          const data = ev.data || {};
          onOperationComplete(stackName, {
            action,
            status: "error",
            message: t("compose.deployFailed", { detail: data.message || t("compose.unknownError") }),
            updatedAt: Date.now(),
          });
          ElMessage.error(t("compose.deployFailed", { detail: data.message || t("compose.unknownError") }));
        }
      },
    });

    if (!completed) {
      completed = true;
      if (controller.signal.aborted) {
        onOperationComplete(stackName, {
          action,
          status: "error",
          message: t("stack.confirm.cancelled"),
          updatedAt: Date.now(),
        });
        return;
      }
      onOperationComplete(stackName, {
        action,
        status: "success",
        message: t("compose.deployCompleted"),
        updatedAt: Date.now(),
      });
      ElMessage.success(payload.isAdd ? t("compose.createdAndDeployed") : t("compose.deployedAndSaved"));
      emit("refresh");
    }
  } catch (e: any) {
    if (completed) return;
    completed = true;
    const detail = e.message || t("compose.unknownError");
    onOperationComplete(stackName, {
      action,
      status: "error",
      message: t("compose.deployFailed", { detail }),
      updatedAt: Date.now(),
    });
    ElMessage.error(t("compose.deployFailed", { detail }));
  }
}

// ── Legacy drawer state ────────────────────────────────────────

const logDrawerVisible = ref(false);
const currentLogStack = ref("");
const composeDrawerVisible = ref(false);
const currentComposeStack = ref("");
const logTailVisible = ref(false);
const currentTailStack = ref("");
const currentTailContent = ref("");

const operationStates = reactive<Record<string, OperationState>>({});

function showLogTail(stackName: string) {
  const state = operationStates[stackName];
  if (state?.logTail) {
    currentTailStack.value = stackName;
    currentTailContent.value = state.logTail;
    logTailVisible.value = true;
  }
}

function statusLabel(status: string): string {
  if (status === "running" || status === "active") return t("stackStatus.running");
  if (status === "exited") return t("stackStatus.exited");
  if (status === "stopped" || status === "inactive") return t("stackStatus.stopped");
  if (status === "partially running" || status === "partial") return t("stackStatus.partial");
  return status || t("stackStatus.unknown");
}

function stackStatusType(status: string): string {
  if (status === "running" || status === "active") return "online";
  if (status === "exited") return "offline";
  if (status === "stopped" || status === "inactive") return "unknown";
  return "degraded";
}

function stackTagType(status: string): "success" | "warning" | "info" | "danger" {
  if (status === "running" || status === "active") return "success";
  if (status === "exited") return "info";
  if (status === "stopped" || status === "inactive") return "info";
  if (status === "partially running" || status === "partial") return "warning";
  return "info";
}

function onIconError(event: Event) {
  const img = event.target as HTMLImageElement;
  if (img) {
    img.style.display = "none";
  }
}

function openLogs(stackName: string) {
  currentLogStack.value = stackName;
  logDrawerVisible.value = true;
}

function openCompose(stackName: string) {
  currentComposeStack.value = stackName;
  composeDrawerVisible.value = true;
}
</script>

<style scoped>
.stack-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.stack-card {
  border: 1px solid var(--border-subtle) !important;
  background: var(--stack-card-bg, rgba(11, 18, 32, 0.78)) !important;
}
.stack-card.is-stopped {
  border-style: dashed !important;
  opacity: 0.75;
}
.stack-card.is-stopped:hover {
  opacity: 0.95;
}
.stack-card.is-stopped .stack-header-left :deep(.el-icon) {
  color: var(--text-muted) !important;
}
.stack-card.is-stopped .stack-icon-img {
  filter: grayscale(100%);
  opacity: 0.55;
}
.stack-card.is-stopped .stack-name {
  color: var(--text-secondary);
}
.stack-card :deep(.el-card__body) {
  padding: 14px 16px;
}
.stack-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  min-height: 32px;
}
.stack-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  min-height: 32px;
  line-height: 1;
}
.stack-icon-img {
  width: 18px;
  height: 18px;
  border-radius: 3px;
  object-fit: contain;
  flex-shrink: 0;
}
.stack-header-right {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  line-height: 1;
}
.stack-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 20px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stack-service-count {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 20px;
  white-space: nowrap;
}
/* ── Operation status line ───────────────────────────────── */
.stack-operation-status {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
}
.stack-operation-status.op-running {
  background: rgba(59, 130, 246, 0.10);
  color: var(--accent-blue);
}
.stack-operation-status.op-success {
  background: rgba(22, 163, 74, 0.10);
  color: var(--success);
}
.stack-operation-status.op-error {
  background: rgba(220, 38, 38, 0.10);
  color: var(--danger);
}
.stack-operation-status.op-timeout {
  background: rgba(217, 119, 6, 0.10);
  color: var(--warning);
}
.op-message {
  flex: 1;
  min-width: 0;
}
/* ── Stack services ───────────────────────────────────────── */
.stack-services {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.service-row {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 0 8px;
  border-radius: 6px;
  background: var(--stack-service-bg, rgba(5, 9, 20, 0.35));
  font-size: 13px;
  line-height: 1;
}
.service-row:hover {
  background: var(--stack-service-hover-bg, rgba(25, 40, 70, 0.35));
}
.service-name {
  color: var(--text-primary);
  font-weight: 500;
  line-height: 20px;
}
.service-status {
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 20px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* ── Log tail dialog ──────────────────────────────────────── */
.log-tail-content {
  background: #1e1e2e;
  color: #cdd6f4;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  padding: 16px;
  border-radius: 6px;
  max-height: 60vh;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.stack-header :deep(.el-button) {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.stack-header :deep(.el-tag) {
  display: inline-flex;
  align-items: center;
  height: 22px;
}
</style>
