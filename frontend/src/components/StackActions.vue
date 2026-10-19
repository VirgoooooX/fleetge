<template>
  <div class="rect-dock" :class="{ 'is-large': size === 'large', 'has-settings': !!$slots.settings }">
    <template v-if="$slots.settings">
      <slot name="settings" />
      <span class="capsule-divider" />
    </template>
    <!-- Action Controls Subgroup -->
    <div class="capsule-subgroup">
      <el-tooltip :content="t('stack.action.start')" placement="top">
        <button
          class="rect-btn color-online"
          :disabled="loading !== null || deleting"
          :aria-label="t('stack.action.startStack')"
          @click="confirmAndRun('start', t('stack.action.start'))"
        >
          <el-icon v-if="loading === 'start'" class="is-loading"><Loading /></el-icon>
          <el-icon v-else><VideoPlay /></el-icon>
        </button>
      </el-tooltip>

      <el-tooltip :content="t('stack.action.stop')" placement="top">
        <button
          class="rect-btn color-danger"
          :disabled="loading !== null || deleting"
          :aria-label="t('stack.action.stopStack')"
          @click="confirmAndRun('stop', t('stack.action.stop'))"
        >
          <el-icon v-if="loading === 'stop'" class="is-loading"><Loading /></el-icon>
          <el-icon v-else><VideoPause /></el-icon>
        </button>
      </el-tooltip>

      <el-tooltip :content="t('stack.action.down')" placement="top">
        <button
          class="rect-btn color-danger"
          :disabled="loading !== null || deleting"
          :aria-label="t('stack.action.downStack')"
          @click="confirmAndRun('down', t('stack.action.down'))"
        >
          <el-icon v-if="loading === 'down'" class="is-loading"><Loading /></el-icon>
          <el-icon v-else><SwitchButton /></el-icon>
        </button>
      </el-tooltip>

      <el-tooltip :content="t('stack.action.restart')" placement="top">
        <button
          class="rect-btn color-primary"
          :disabled="loading !== null || deleting"
          :aria-label="t('stack.action.restartStack')"
          @click="confirmAndRun('restart', t('stack.action.restart'))"
        >
          <el-icon v-if="loading === 'restart'" class="is-loading"><Loading /></el-icon>
          <el-icon v-else><Refresh /></el-icon>
        </button>
      </el-tooltip>

      <el-tooltip :content="t('stack.action.update')" placement="top">
        <button
          class="rect-btn color-warning"
          :disabled="loading !== null || deleting || persistedUpdateActive"
          :aria-label="t('stack.action.updateStack')"
          @click="confirmAndRun('update', t('stack.action.update'))"
        >
          <el-icon v-if="loading === 'update'" class="is-loading"><Loading /></el-icon>
          <el-icon v-else><Top /></el-icon>
        </button>
      </el-tooltip>
    </div>

    <span v-if="!managementMenu" class="capsule-divider" />

    <!-- Delete Control -->
    <el-tooltip v-if="!managementMenu" :content="t('stack.action.delete')" placement="top">
      <button
        class="rect-btn danger-trash"
        :disabled="loading !== null || deleting"
        :aria-label="t('stack.action.deleteStack')"
        @click="confirmAndDelete"
      >
        <el-icon v-if="deleting" class="is-loading"><Loading /></el-icon>
        <el-icon v-else><Delete /></el-icon>
      </button>
    </el-tooltip>

    <!-- Additional Workspace Controls -->
    <template v-if="showCompose || showLogs || showDetail || appUrl || managementMenu">
      <span class="capsule-divider" />

      <div class="capsule-subgroup">
        <el-tooltip v-if="appUrl" :content="t('stackGroup.openApp')" placement="top">
          <button
            class="rect-btn"
            :disabled="loading !== null || deleting"
            @click="openApp"
          >
            <el-icon><Link /></el-icon>
          </button>
        </el-tooltip>

        <el-tooltip v-if="showCompose && !managementMenu" :content="t('stackGroup.editCompose')" placement="top">
          <button
            class="rect-text-btn"
            :disabled="loading !== null || deleting || !canEditCompose"
            @click="emit('compose')"
          >
            <el-icon><EditPen /></el-icon>
            <span>Compose</span>
          </button>
        </el-tooltip>

        <el-tooltip v-if="showLogs" :content="t('stackGroup.viewLogs')" placement="top">
          <button
            class="rect-btn"
            :disabled="loading !== null || deleting"
            @click="emit('logs')"
          >
            <el-icon><Document /></el-icon>
          </button>
        </el-tooltip>

        <el-tooltip v-if="showDetail" :content="t('workspace.viewDetail')" placement="top">
          <button
            class="rect-btn"
            :disabled="loading !== null || deleting"
            @click="emit('detail')"
          >
            <el-icon><Document /></el-icon>
          </button>
        </el-tooltip>

        <el-dropdown
          v-if="managementMenu"
          trigger="click"
          placement="bottom-end"
          popper-class="stack-management-menu"
          :disabled="loading !== null || deleting"
          @command="handleManagementCommand"
        >
          <button
            class="rect-btn"
            :disabled="loading !== null || deleting"
            :aria-label="t('stackGroup.moreActions')"
            :title="t('stackGroup.moreActions')"
          >
            <el-icon><MoreFilled /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item
                v-if="showCompose"
                command="compose"
                :disabled="!canEditCompose"
              >
                <el-icon><EditPen /></el-icon>
                {{ t('stackGroup.editCompose') }}
              </el-dropdown-item>
              <el-dropdown-item class="management-delete-item" command="delete" divided>
                <el-icon><Delete /></el-icon>
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
  VideoPlay,
  VideoPause,
  Refresh,
  Top,
  Delete,
  SwitchButton,
  EditPen,
  Document,
  Loading,
  Link,
  MoreFilled
} from "@element-plus/icons-vue";
import { streamSse } from "@/api/sse";
import { useConfirm, STACK_TONE_MAP } from "@/composables/useConfirm";
import { useDashboardStore, type UpdateRunItem } from "@/stores/dashboard";

export type OperationState = {
  hostId?: string;
  action: string;
  status: "running" | "success" | "error" | "timeout" | "uncertain" | "skipped";
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
const deleting = ref(false);
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

let sseAbortController: AbortController | null = null;

onBeforeUnmount(() => {
  if (sseAbortController) {
    sseAbortController.abort();
    sseAbortController = null;
  }
});

const riskKeys: Record<string, string> = {
  start: "stack.risk.start",
  stop: "stack.risk.stop",
  down: "stack.risk.down",
  restart: "stack.risk.restart",
  update: "stack.risk.update",
};

const actionTimeouts: Record<string, number> = {
  start: 120000,
  stop: 120000,
  down: 120000,
  restart: 120000,
  update: 600000,
};

async function confirmAndRun(action: string, label: string) {
  try {
    await confirm(
      t("stack.confirm.message", {
        action: label,
        name: props.stackName,
        risk: t(riskKeys[action]),
      }),
      t("stack.confirm.title", { action: label }),
      {
        tone: STACK_TONE_MAP[action] || "info",
        confirmButtonText: t("stack.confirm.ok"),
        cancelButtonText: t("stack.confirm.cancel"),
        confirmButtonClass: "pg-confirm-btn",
      }
    );
  } catch {
    return;
  }

  const currentStackName = props.stackName;
  const currentHostId = props.hostId;
  if (action === "update") {
    void submitManualUpdate(currentStackName, label);
    return;
  }
  const startedAt = Date.now();
  const controller = new AbortController();
  sseAbortController = controller;

  const runningState: OperationState = {
    hostId: currentHostId,
    action,
    status: "running",
    message: t("stack.confirm.running", { action: label }),
    updatedAt: startedAt,
    abort: () => {
      controller.abort();
    }
  };
  emit("operation-start", currentStackName, runningState);
  loading.value = action;

  let completed = false;
  const timeoutMs = actionTimeouts[action] || 120000;

  try {
    const cols = props.showDetail ? 55 : 110;
    const rows = props.showDetail ? 15 : 24;
    const url = `/api/hosts/${currentHostId}/stacks/${encodeURIComponent(currentStackName)}/${action}?cols=${cols}&rows=${rows}`;

    await streamSse({
      url,
      method: "POST",
      timeoutMs,
      signal: controller.signal,
      onTimeout: () => {
        if (completed) return;
        completed = true;
        const timeoutState: OperationState = {
          action,
          status: "timeout",
          message: t("stack.confirm.timeout"),
          updatedAt: Date.now(),
        };
        emit("operation-complete", currentStackName, timeoutState);
        ElMessage.warning(timeoutState.message);
      },
      onEvent: (ev) => {
        if (props.hostId !== currentHostId || props.stackName !== currentStackName) return;
        if (ev.event === "chunk") {
          emit("terminal-chunk", currentStackName, { hostId: currentHostId, action, chunk: ev.data?.raw ?? ev.rawData });
        } else if (ev.event === "line") {
          emit("terminal-chunk", currentStackName, { hostId: currentHostId, action, chunk: ev.data?.text ?? ev.rawData });
        } else if (ev.event === "complete") {
          completed = true;

          const data = ev.data || {};
          const finalStatus = data.status === "success" ? "success" : "error";
          const completeState: OperationState = {
            hostId: currentHostId,
            action,
            status: finalStatus,
            message: finalStatus === "success"
              ? t("stack.confirm.success", { action: label })
              : data.message || t("stack.confirm.failure", { action: label }),
            updatedAt: Date.now(),
          };
          emit("operation-complete", currentStackName, completeState);
          if (finalStatus === "success") {
            ElMessage.success(completeState.message);
            emit("refresh");
          } else {
            ElMessage.error(completeState.message);
          }
        } else if (ev.event === "error") {
          completed = true;

          const data = ev.data || {};
          const errorState: OperationState = {
            action,
            status: "error",
            message: data.message || t("stack.confirm.failure", { action: label }),
            updatedAt: Date.now(),
          };
          emit("operation-complete", currentStackName, errorState);
          ElMessage.error(errorState.message);
        }
      },
    });

    if (!completed) {
      completed = true;
      if (controller.signal.aborted) {
        const cancelState: OperationState = {
          action,
          status: "error",
          message: t("stack.confirm.cancelled"),
          updatedAt: Date.now(),
        };
        emit("operation-complete", currentStackName, cancelState);
        return;
      }
      const errorState: OperationState = {
        hostId: currentHostId,
        action,
        status: "error",
        message: t("stack.confirm.noResult"),
        updatedAt: Date.now(),
      };
      emit("operation-complete", currentStackName, errorState);
      ElMessage.warning(errorState.message);
    }
  } catch (e: any) {
    if (completed) return;
    completed = true;

    if (controller.signal.aborted) {
      const cancelState: OperationState = {
        action,
        status: "error",
        message: t("stack.confirm.cancelled"),
        updatedAt: Date.now(),
      };
      emit("operation-complete", currentStackName, cancelState);
      return;
    }

    const errorDetail = e.message || t("stack.confirm.unknownError");
    const errorState: OperationState = {
      action,
      status: "error",
      message: t("stack.confirm.failure", { action: label }) + ": " + errorDetail,
      updatedAt: Date.now(),
    };
    emit("operation-complete", currentStackName, errorState);
    ElMessage.error(errorState.message);
  } finally {
    if (loading.value === action) {
      loading.value = null;
    }
    if (sseAbortController === controller) {
      sseAbortController = null;
    }
  }
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
  const isCurrent = () => !controller.signal.aborted && props.hostId === hostId && props.stackName === stackName;
  let cursor = 0;
  let completed = false;
  let reportedDisconnect = false;
  emit("operation-start", stackName, {
    hostId, action: "update", status: "running",
    message: t(run.status === "queued" ? "workspace.updateRunStatus.queued" : "stack.confirm.running", { action: t("stack.action.update") }),
    updatedAt: Date.now(),
    abort: () => controller.abort(),
  });
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
              : outcome === "uncertain" ? "uncertain" : outcome === "skipped" ? "skipped" : "error";
            const message = t(outcome === "success" ? "stack.confirm.updateVerified"
              : outcome === "uncertain" ? "stack.confirm.updateUncertain"
                : outcome === "skipped" ? "workspace.updateRunStatus.skipped" : "stack.confirm.failure", { action: t("stack.action.update") });
            if (outcome !== "success" && event.data?.message) {
              emit("terminal-chunk", stackName, { hostId, action: "update", chunk: `\r\n${event.data.message}\r\n` });
            }
            emit("operation-complete", stackName, { hostId, action: "update", status, message, updatedAt: Date.now() });
            if (status === "success") { ElMessage.success(message); emit("refresh"); }
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
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

async function submitManualUpdate(stackName: string, label: string) {
  loading.value = "update";
  const hostId = props.hostId;
  emit("operation-start", stackName, {
    hostId, action: "update", status: "running", message: t("workspace.updateSubmitting"), updatedAt: Date.now(),
  });
  try {
    const batch = await dashboardStore.submitUpdateRuns(hostId, "manual", [stackName]);
    const run = batch.items.find((item) => item.stack_name === stackName);
    if (!run) throw new Error(t("workspace.updateRunMissing"));
    if (props.hostId === hostId && props.stackName === stackName) void viewUpdateRun(run);
  } catch (error: any) {
    if (props.hostId !== hostId || props.stackName !== stackName) return;
    const detail = error?.response?.data?.detail;
    const message = (typeof detail === "string" ? detail : detail?.message) || error?.message || t("stack.confirm.failure", { action: label });
    emit("operation-complete", stackName, { hostId, action: "update", status: "error", message, updatedAt: Date.now() });
    ElMessage.error(message);
  } finally {
    loading.value = null;
  }
}

async function confirmAndDelete() {
  try {
    await confirm(
      t("stack.delete.message", { name: props.stackName }),
      t("stack.delete.title"),
      {
        tone: "danger",
        confirmButtonText: t("stack.delete.ok"),
        cancelButtonText: t("stack.confirm.cancel"),
        confirmButtonClass: "pg-confirm-btn",
      }
    );
  } catch {
    return;
  }

  deleting.value = true;
  const currentStackName = props.stackName;
  const action = "delete";
  const label = t("stack.action.delete");
  const controller = new AbortController();
  sseAbortController = controller;
  let completed = false;

  const runningState: OperationState = {
    action,
    status: "running",
    message: t("stack.confirm.running", { action: label }),
    updatedAt: Date.now(),
    abort: () => controller.abort(),
  };
  emit("operation-start", currentStackName, runningState);

  try {
    const cols = props.showDetail ? 55 : 110;
    const rows = props.showDetail ? 15 : 24;
    const url = `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(currentStackName)}/delete?cols=${cols}&rows=${rows}`;

    await streamSse({
      url,
      method: "POST",
      timeoutMs: 180000,
      signal: controller.signal,
      onTimeout: () => {
        if (completed) return;
        completed = true;
        const timeoutState: OperationState = {
          action,
          status: "timeout",
          message: t("stack.confirm.timeout"),
          updatedAt: Date.now(),
        };
        emit("operation-complete", currentStackName, timeoutState);
        ElMessage.warning(timeoutState.message);
      },
      onEvent: (ev) => {
        if (ev.event === "chunk") {
          emit("terminal-chunk", currentStackName, { action, chunk: ev.data?.raw ?? ev.rawData });
        } else if (ev.event === "line") {
          emit("terminal-chunk", currentStackName, { action, chunk: ev.data?.text ?? ev.rawData });
        } else if (ev.event === "complete") {
          completed = true;
          const data = ev.data || {};
          const finalStatus = data.status === "success" ? "success" : "error";
          const completeState: OperationState = {
            action,
            status: finalStatus,
            message: data.message || (finalStatus === "success"
              ? t("stack.delete.success", { name: currentStackName })
              : t("stack.delete.failure", { name: currentStackName })),
            updatedAt: Date.now(),
          };
          emit("operation-complete", currentStackName, completeState);
          if (finalStatus === "success") {
            ElMessage.success(completeState.message);
            emit("refresh");
          } else {
            ElMessage.error(completeState.message);
          }
        } else if (ev.event === "error") {
          completed = true;
          const data = ev.data || {};
          const errorState: OperationState = {
            action,
            status: "error",
            message: t("stack.delete.failure", { name: currentStackName }) + ": " + (data.message || t("stack.confirm.unknownError")),
            updatedAt: Date.now(),
          };
          emit("operation-complete", currentStackName, errorState);
          ElMessage.error(errorState.message);
        }
      },
    });

    if (!completed && !controller.signal.aborted) {
      const successState: OperationState = {
        action,
        status: "success",
        message: t("stack.delete.success", { name: currentStackName }),
        updatedAt: Date.now(),
      };
      emit("operation-complete", currentStackName, successState);
      ElMessage.success(successState.message);
      emit("refresh");
    }
  } catch (e: any) {
    if (completed) return;
    const detail = e.response?.data?.detail || e.message || t("stack.confirm.unknownError");
    const errorState: OperationState = {
      action,
      status: "error",
      message: t("stack.delete.failure", { name: currentStackName }) + ": " + detail,
      updatedAt: Date.now(),
    };
    emit("operation-complete", currentStackName, errorState);
    ElMessage.error(errorState.message);
  } finally {
    deleting.value = false;
    if (sseAbortController === controller) {
      sseAbortController = null;
    }
  }
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
  transition: all 180ms cubic-bezier(0.4, 0, 0.2, 1);
  color: var(--text-secondary);
  outline: none;
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
</style>
