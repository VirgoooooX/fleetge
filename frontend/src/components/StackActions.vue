<template>
  <div class="rect-dock" :class="{ 'is-large': size === 'large', 'has-settings': !!$slots.settings }">
    <template v-if="$slots.settings">
      <slot name="settings" />
      <span class="capsule-divider" />
    </template>
    <!-- Action Controls Subgroup -->
    <div class="capsule-subgroup">
      <el-tooltip v-for="control in lifecycleControls" :key="control.action" :content="t(`stack.action.${control.action}`)" placement="top">
        <button
          type="button"
          class="rect-btn"
          :class="control.tone"
          :disabled="busy || (control.action === 'update' && persistedUpdateActive)"
          :aria-label="t(`stack.action.${control.action}Stack`)"
          @click="confirmAndRun(control.action)"
        >
          <el-icon :class="{ 'is-loading': loading === control.action }">
            <component :is="loading === control.action ? LoaderCircle : control.icon" />
          </el-icon>
        </button>
      </el-tooltip>
    </div>

    <span v-if="!managementMenu" class="capsule-divider" />

    <!-- Delete Control -->
    <el-tooltip v-if="!managementMenu" :content="t('stack.action.delete')" placement="top">
      <button
        type="button"
        class="rect-btn danger-trash"
        :disabled="busy"
        :aria-label="t('stack.action.deleteStack')"
        @click="confirmAndDelete"
      >
        <el-icon v-if="deleting" class="is-loading"><LoaderCircle /></el-icon>
        <el-icon v-else><Trash2 /></el-icon>
      </button>
    </el-tooltip>

    <!-- Additional Workspace Controls -->
    <template v-if="showCompose || showLogs || showDetail || appUrl || managementMenu">
      <span class="capsule-divider" />

      <div class="capsule-subgroup">
        <el-tooltip v-if="appUrl" :content="t('stackGroup.openApp')" placement="top">
          <button
            type="button"
            class="rect-btn"
            :disabled="busy"
            :aria-label="t('stackGroup.openApp')"
            @click="openApp"
          >
            <el-icon><Link2 /></el-icon>
          </button>
        </el-tooltip>

        <el-tooltip v-if="showCompose && !managementMenu" :content="t('stackGroup.editCompose')" placement="top">
          <button
            type="button"
            class="rect-text-btn"
            :disabled="busy || !canEditCompose"
            @click="emit('compose')"
          >
            <el-icon><Pencil /></el-icon>
            <span>Compose</span>
          </button>
        </el-tooltip>

        <el-tooltip v-if="showLogs" :content="t('stackGroup.viewLogs')" placement="top">
          <button
            type="button"
            class="rect-btn"
            :disabled="busy"
            :aria-label="t('stackGroup.viewLogs')"
            @click="emit('logs')"
          >
            <el-icon><FileText /></el-icon>
          </button>
        </el-tooltip>

        <el-tooltip v-if="showDetail" :content="t('workspace.viewDetail')" placement="top">
          <button
            type="button"
            class="rect-btn"
            :disabled="busy"
            :aria-label="t('workspace.viewDetail')"
            @click="emit('detail')"
          >
            <el-icon><FileText /></el-icon>
          </button>
        </el-tooltip>

        <el-dropdown
          v-if="managementMenu"
          trigger="click"
          placement="bottom-end"
          popper-class="stack-management-menu"
          :disabled="busy"
          @command="handleManagementCommand"
        >
          <button
            type="button"
            class="rect-btn"
            :disabled="busy"
            :aria-label="t('stackGroup.moreActions')"
            :title="t('stackGroup.moreActions')"
          >
            <el-icon><MoreHorizontal /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-if="showCompose"
                command="compose"
                :disabled="!canEditCompose"
              >
                <el-icon><Pencil /></el-icon>
                {{ t('stackGroup.editCompose') }}
              </el-dropdown-item>
              <el-dropdown-item class="management-delete-item" command="delete" divided>
                <el-icon><Trash2 /></el-icon>
                {{ t('stack.action.delete') }}
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onBeforeUnmount, watch } from "vue";
import { ElMessage } from "element-plus";
import { useI18n } from "vue-i18n";
import {
  ArrowUp,
  FileText,
  Link2,
  LoaderCircle,
  MoreHorizontal,
  Pause,
  Pencil,
  Play,
  Power,
  RefreshCw,
  Trash2,
} from "@lucide/vue";
import { streamSse } from "@/api/sse";
import { useSseOperation } from "@/composables/useSseOperation";
import { useConfirm, STACK_TONE_MAP } from "@/composables/useConfirm";
import { useDashboardStore, type UpdateRunItem } from "@/stores/dashboard";

export type OperationState = {
  hostId?: string;
  action: string;
  status: "running" | "success" | "error" | "timeout" | "partial" | "uncertain" | "skipped";
  message: string;
  logTail?: string;
  updatedAt: number;
  abort?: () => void;
};

export type TerminalChunkEvent = {
  hostId?: string;
  action: string;
  chunk: string;
};

const props = withDefaults(
  defineProps<{
    hostId: string;
    stackName: string;
    showCompose?: boolean;
    showLogs?: boolean;
    showDetail?: boolean;
    canEditCompose?: boolean;
    size?: "default" | "large";
    appUrl?: string;
    managementMenu?: boolean;
    restoreCompletedUpdate?: boolean;
  }>(),
  {
    showCompose: false,
    showLogs: false,
    showDetail: false,
    canEditCompose: true,
    size: "default",
    appUrl: "",
    managementMenu: false,
    restoreCompletedUpdate: false,
  }
);

const emit = defineEmits<{
  "operation-start": [stackName: string, payload: OperationState];
  "operation-complete": [stackName: string, payload: OperationState];
  "terminal-chunk": [stackName: string, payload: TerminalChunkEvent];
  refresh: [];
  compose: [];
  logs: [];
  detail: [];
}>();

const loading = ref<string | null>(null);
const deleting = computed(() => loading.value === "delete");
const confirming = ref(false);
const busy = computed(() => loading.value !== null || confirming.value);
const lifecycleControls = [
  { action: "start", tone: "color-online", icon: Play },
  { action: "stop", tone: "color-danger", icon: Pause },
  { action: "down", tone: "color-danger", icon: Power },
  { action: "restart", tone: "color-primary", icon: RefreshCw },
  { action: "update", tone: "color-warning", icon: ArrowUp },
] as const;
type LifecycleAction = (typeof lifecycleControls)[number]["action"];
const { t } = useI18n();
const { confirm } = useConfirm();
const dashboardStore = useDashboardStore();
const persistedUpdateActive = computed(() => {
  const run = dashboardStore.updateRunForStack(props.hostId, props.stackName);
  return run?.status === "queued" || run?.status === "running";
});

function openApp() {
  if (props.appUrl) {
    window.open(props.appUrl, "_blank", "noopener,noreferrer");
  }
}

function handleManagementCommand(command: string) {
  if (command === "compose") {
    emit("compose");
    return;
  }
  if (command === "delete") {
    void confirmAndDelete();
  }
}

const operation = useSseOperation();
let mounted = true;
let targetRevision = 0;
let activeCommand: { hostId: string; stackName: string; action: Exclude<LifecycleAction, "update"> | "delete" } | null = null;

function discardCommand() {
  operation.discard();
  if (!activeCommand) return;
  const { hostId, stackName, action } = activeCommand;
  activeCommand = null;
  emit("operation-complete", stackName, {
    hostId, action, status: "error", message: t("stack.confirm.cancelled"), updatedAt: Date.now(),
  });
}

onBeforeUnmount(() => {
  mounted = false;
  discardCommand();
});
watch(() => [props.hostId, props.stackName], () => {
  targetRevision++;
  discardCommand();
  loading.value = null;
});

async function confirmAndRun(action: LifecycleAction | "delete") {
  if (busy.value || (action === "update" && persistedUpdateActive.value)) return;
  const stackName = props.stackName;
  const hostId = props.hostId;
  const label = t(`stack.action.${action}`);
  const isDelete = action === "delete";
  const revision = targetRevision;
  const stillCurrent = () => mounted && targetRevision === revision && props.hostId === hostId && props.stackName === stackName;
  confirming.value = true;
  try {
    await confirm(
      isDelete
        ? t("stack.delete.message", { name: stackName })
        : t("stack.confirm.message", { action: label, name: stackName, risk: t(`stack.risk.${action}`) }),
      isDelete ? t("stack.delete.title") : t("stack.confirm.title", { action: label }),
      {
        tone: isDelete ? "danger" : STACK_TONE_MAP[action] || "info",
        confirmButtonText: t(isDelete ? "stack.delete.ok" : "stack.confirm.ok"),
        cancelButtonText: t("stack.confirm.cancel"),
        confirmButtonClass: "pg-confirm-btn",
      }
    );
  } catch {
    return;
  } finally {
    confirming.value = false;
  }
  if (!stillCurrent() || (action === "update" && persistedUpdateActive.value)) return;
  if (action === "update") {
    void submitManualUpdate(stackName, label);
    return;
  }

  loading.value = action;
  activeCommand = { hostId, stackName, action };
  const result = await operation.run({
    hostId, stackName, action,
    cols: props.showDetail ? 55 : 110,
    rows: props.showDetail ? 15 : 24,
    timeoutMs: isDelete ? 180000 : 120000,
    onStart: abort => emit("operation-start", stackName, {
      hostId, action, status: "running", message: t("stack.confirm.running", { action: label }), updatedAt: Date.now(), abort,
    }),
    onChunk: chunk => {
      if (stillCurrent()) emit("terminal-chunk", stackName, { hostId, action, chunk });
    },
  });
  if (!stillCurrent() || !result) return;
  activeCommand = null;
  loading.value = null;

  const success = result.kind === "complete" && result.success;
  const failure = isDelete ? t("stack.delete.failure", { name: stackName }) : t("stack.confirm.failure", { action: label });
  let message = failure;
  if (result.kind === "complete") {
    if (success) message = isDelete ? result.message || t("stack.delete.success", { name: stackName }) : t("stack.confirm.success", { action: label });
    else message = result.message || failure;
  } else if (result.kind === "timeout") message = t("stack.confirm.timeout");
  else if (result.kind === "cancelled") message = t("stack.confirm.cancelled");
  else if (result.kind === "no-result") message = t("stack.confirm.noResult");
  else if (result.kind === "request-error" || isDelete) message = `${failure}: ${result.message || t("stack.confirm.unknownError")}`;
  else message = result.message || failure;

  const status = success ? "success" : result.kind === "timeout" ? "timeout" : "error";
  emit("operation-complete", stackName, { hostId, action, status, message, updatedAt: Date.now() });
  if (success) {
    ElMessage.success(message);
    emit("refresh");
  } else if (result.kind === "timeout" || result.kind === "no-result") ElMessage.warning(message);
  else if (result.kind !== "cancelled") ElMessage.error(message);
}

let updateViewId: number | null = null;
let updateViewController: AbortController | null = null;

watch(
  () => ({ hostId: props.hostId, stackName: props.stackName, run: dashboardStore.updateRunForStack(props.hostId, props.stackName) }),
  (current, previous) => {
    if (previous && (current.hostId !== previous.hostId || current.stackName !== previous.stackName)) {
      updateViewController?.abort();
      updateViewId = null;
    }
    const run = current.run;
    const restoreCompleted = props.restoreCompletedUpdate && run
      && dashboardStore.observedUpdateRunIds[`${current.hostId}/${current.stackName}`] === run.id;
    if (run && (run.status === "running" || restoreCompleted) && run.id !== updateViewId) {
      void viewUpdateRun(run);
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => updateViewController?.abort());

async function viewUpdateRun(run: UpdateRunItem) {
  if (updateViewId === run.id) return;
  updateViewController?.abort();
  updateViewId = run.id;
  const controller = new AbortController();
  updateViewController = controller;
  const hostId = run.host_id;
  const stackName = run.stack_name;
  const isCurrent = () => updateViewController === controller && !controller.signal.aborted && props.hostId === hostId && props.stackName === stackName;
  let cursor = 0;
  let completed = false;
  let reportedDisconnect = false;
  emit("operation-start", stackName, {
    hostId, action: "update", status: "running",
    message: t(run.status === "queued" ? "workspace.updateRunStatus.queued" : "stack.confirm.running", { action: t("stack.action.update") }),
    updatedAt: Date.now(),
    abort: () => controller.abort(),
  });
  try {
    while (isCurrent() && !completed) {
      try {
        await streamSse({
          url: `/api/hosts/${encodeURIComponent(hostId)}/stacks/${encodeURIComponent(stackName)}/update-runs/${encodeURIComponent(run.request_id)}/stream?after=${cursor}`,
          signal: controller.signal,
          onEvent: (event) => {
            if (!isCurrent()) return;
            if (event.event === "chunk") {
              emit("terminal-chunk", stackName, { hostId, action: "update", chunk: event.data?.raw || "" });
              cursor = event.data?.cursor ?? cursor;
            } else if (event.event === "complete") {
              completed = true;
              const outcome = event.data?.outcome;
              const status: OperationState["status"] = outcome === "success" ? "success"
                : outcome === "partial" ? "partial" : outcome === "uncertain" ? "uncertain" : outcome === "skipped" ? "skipped" : "error";
              const message = t(outcome === "success" ? "stack.confirm.updateVerified"
                : outcome === "partial" ? "workspace.updateRunStatus.partial"
                : outcome === "uncertain" ? "stack.confirm.updateUncertain"
                  : outcome === "skipped" ? "workspace.updateRunStatus.skipped" : "stack.confirm.failure", { action: t("stack.action.update") });
              if (outcome !== "success" && event.data?.message) {
                emit("terminal-chunk", stackName, { hostId, action: "update", chunk: `\r\n${event.data.message}\r\n` });
              }
              emit("operation-complete", stackName, { hostId, action: "update", status, message, updatedAt: Date.now() });
              if (status === "success" || status === "partial") emit("refresh");
              if (status === "success") ElMessage.success(message);
              else if (status === "error") ElMessage.error(message);
              else ElMessage.warning(message);
              void dashboardStore.fetchUpdateRuns(hostId).catch(() => undefined);
            }
          },
        });
      } catch { /* A lost viewer does not change the backend run result. */ }
      if (!isCurrent() || completed) break;
      if (!reportedDisconnect) {
        emit("terminal-chunk", stackName, { hostId, action: "update", chunk: `\r\n${t("stack.confirm.reconnectingUpdate")}\r\n` });
        reportedDisconnect = true;
      }
      await new Promise<void>(resolve => {
        const retry = setTimeout(finish, 2000);
        function finish() {
          clearTimeout(retry);
          controller.signal.removeEventListener("abort", finish);
          resolve();
        }
        controller.signal.addEventListener("abort", finish, { once: true });
      });
    }
  } finally {
    if (updateViewController === controller) updateViewController = null;
  }
}

async function submitManualUpdate(stackName: string, label: string) {
  loading.value = "update";
  const hostId = props.hostId;
  const revision = targetRevision;
  const stillCurrent = () => mounted && targetRevision === revision && props.hostId === hostId && props.stackName === stackName;
  emit("operation-start", stackName, {
    hostId, action: "update", status: "running", message: t("workspace.updateSubmitting"), updatedAt: Date.now(),
  });
  try {
    const batch = await dashboardStore.submitUpdateRuns(hostId, "manual", [stackName]);
    const run = batch.items.find((item) => item.stack_name === stackName);
    if (!run) throw new Error(t("workspace.updateRunMissing"));
    if (stillCurrent()) void viewUpdateRun(run);
  } catch (error: any) {
    if (!stillCurrent()) return;
    const detail = error?.response?.data?.detail;
    const message = (typeof detail === "string" ? detail : detail?.message) || error?.message || t("stack.confirm.failure", { action: label });
    emit("operation-complete", stackName, { hostId, action: "update", status: "error", message, updatedAt: Date.now() });
    ElMessage.error(message);
  } finally {
    if (stillCurrent()) loading.value = null;
  }
}

function confirmAndDelete() {
  void confirmAndRun("delete");
}
</script>

<style scoped>
.rect-dock {
  display: inline-flex;
  align-items: center;
  background: rgba(15, 23, 42, 0.25);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 1.5px 5px;
  gap: 3px;
  transition: border-color 200ms ease, background 200ms ease;
  line-height: 1;
}

[data-theme="light"] .rect-dock {
  background: rgba(240, 244, 250, 0.7);
  border-color: var(--border-subtle);
}

.rect-dock:hover {
  border-color: var(--border-strong);
}

.capsule-subgroup {
  display: inline-flex;
  align-items: center;
  gap: 1px;
}

.capsule-divider {
  width: 1px;
  height: 14px;
  background: rgba(148, 163, 184, 0.2);
  margin: 0 5px;
}

.rect-btn, .rect-text-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition:
    color var(--duration-normal, 180ms) var(--ease-standard, cubic-bezier(0.4, 0, 0.2, 1)),
    background-color var(--duration-normal, 180ms) var(--ease-standard, cubic-bezier(0.4, 0, 0.2, 1)),
    box-shadow var(--duration-normal, 180ms) var(--ease-standard, cubic-bezier(0.4, 0, 0.2, 1)),
    transform var(--duration-normal, 180ms) var(--ease-standard, cubic-bezier(0.4, 0, 0.2, 1));
  color: var(--text-secondary);
  position: relative;
}

.rect-btn {
  width: 30px;
  height: 30px;
  border-radius: 6px;
}

.rect-text-btn {
  height: 30px;
  padding: 0 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 700;
  gap: 5px;
}

.rect-btn:disabled, .rect-text-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
  transform: none !important;
  box-shadow: none !important;
}

/* Color definition for Icons in passive state */
.color-online { color: rgba(52, 211, 153, 0.95); }
.color-danger { color: rgba(248, 113, 113, 0.95); }
.color-primary { color: rgba(96, 165, 250, 0.95); }
.color-warning { color: rgba(251, 191, 36, 0.95); }
.danger-trash { color: var(--text-muted); }

/* Hover effects with scale & soft box-shadow glow */
.color-online:not(:disabled):hover {
  background: rgba(52, 211, 153, 0.15);
  color: var(--success) !important;
  box-shadow: 0 0 6px rgba(52, 211, 153, 0.35);
  transform: scale(1.1);
}

.color-danger:not(:disabled):hover {
  background: rgba(248, 113, 113, 0.15);
  color: var(--danger) !important;
  box-shadow: 0 0 6px rgba(248, 113, 113, 0.35);
  transform: scale(1.1);
}

.color-primary:not(:disabled):hover {
  background: rgba(96, 165, 250, 0.15);
  color: var(--accent-blue) !important;
  box-shadow: 0 0 6px rgba(96, 165, 250, 0.35);
  transform: scale(1.1);
}

.color-warning:not(:disabled):hover {
  background: rgba(251, 191, 36, 0.15);
  color: var(--warning) !important;
  box-shadow: 0 0 6px rgba(251, 191, 36, 0.35);
  transform: scale(1.1);
}

.danger-trash:not(:disabled):hover {
  background: rgba(220, 38, 38, 0.16);
  color: var(--danger) !important;
  box-shadow: 0 0 6px rgba(220, 38, 38, 0.35);
  transform: scale(1.1);
}

/* Neutral button hover styles */
.rect-btn:not([class*="color-"]):not(:disabled):hover {
  background: rgba(148, 163, 184, 0.16);
  color: var(--text-primary);
  transform: scale(1.1);
}

.rect-text-btn:not(:disabled):hover {
  background: rgba(148, 163, 184, 0.16);
  color: var(--text-primary);
  transform: scale(1.05);
}

.rect-btn :deep(.el-icon),
.rect-text-btn :deep(.el-icon) {
  font-size: 18px;
}

@media (max-width: 720px) {
  .rect-dock.has-settings.is-large { gap: 2px; }
  .rect-dock.has-settings.is-large .rect-btn { width: 30px; height: 32px; }
  .rect-dock.has-settings.is-large .capsule-divider { margin: 0 3px; }
}

/* Large size variations */
.rect-dock.is-large {
  padding: 2.5px 6px;
  border-radius: 10px;
  gap: 4px;
}

.rect-dock.is-large .rect-btn {
  width: 36px;
  height: 36px;
  border-radius: 8px;
}

.rect-dock.is-large .rect-text-btn {
  height: 36px;
  padding: 0 14px;
  border-radius: 8px;
  font-size: 13px;
  gap: 6px;
}

.rect-dock.is-large .capsule-divider {
  height: 18px;
  margin: 0 6px;
}

.rect-dock.is-large .rect-btn :deep(.el-icon),
.rect-dock.is-large .rect-text-btn :deep(.el-icon) {
  font-size: 22px;
}

:global(.stack-management-menu .management-delete-item) {
  color: var(--danger);
}
@media (prefers-reduced-motion: reduce) {
  .rect-dock,
  .rect-btn,
  .rect-text-btn {
    transition: none;
  }

  .is-loading {
    animation: none;
  }
}
</style>
