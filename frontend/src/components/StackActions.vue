<template>
  <div class="rect-dock">
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
          :disabled="loading !== null || deleting"
          :aria-label="t('stack.action.updateStack')"
          @click="confirmAndRun('update', t('stack.action.update'))"
        >
          <el-icon v-if="loading === 'update'" class="is-loading"><Loading /></el-icon>
          <el-icon v-else><Top /></el-icon>
        </button>
      </el-tooltip>
    </div>

    <span class="capsule-divider" />

    <!-- Delete Control -->
    <el-tooltip :content="t('stack.action.delete')" placement="top">
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
    <template v-if="showCompose || showLogs || showDetail">
      <span class="capsule-divider" />

      <div class="capsule-subgroup">
        <el-tooltip v-if="showCompose" :content="t('stackGroup.editCompose')" placement="top">
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
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onBeforeUnmount } from "vue";
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
  Loading
} from "@element-plus/icons-vue";
import { streamSse } from "@/api/sse";
import { useConfirm, STACK_TONE_MAP } from "@/composables/useConfirm";

export type OperationState = {
  action: string;
  status: "running" | "success" | "error" | "timeout";
  message: string;
  logTail?: string;
  updatedAt: number;
  abort?: () => void;
};

export type TerminalChunkEvent = {
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
  }>(),
  {
    showCompose: false,
    showLogs: false,
    showDetail: false,
    canEditCompose: true,
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
  const startedAt = Date.now();
  const controller = new AbortController();
  sseAbortController = controller;

  const runningState: OperationState = {
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
    const url = `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(currentStackName)}/${action}?cols=${cols}&rows=${rows}`;

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
            message: data.message || t(finalStatus === "success" ? "stack.confirm.success" : "stack.confirm.failure", { action: label }),
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
      const successState: OperationState = {
        action,
        status: "success",
        message: t("stack.confirm.success", { action: label }),
        updatedAt: Date.now(),
      };
      emit("operation-complete", currentStackName, successState);
      ElMessage.success(successState.message);
      emit("refresh");
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
  border-radius: 7px;
  padding: 3px 5px;
  gap: 2px;
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
  height: 12px;
  background: rgba(148, 163, 184, 0.2);
  margin: 0 4px;
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
  width: 26px;
  height: 26px;
  border-radius: 5px;
}

.rect-text-btn {
  height: 26px;
  padding: 0 8px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 700;
  gap: 4px;
}

.rect-btn:disabled, .rect-text-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
  transform: none !important;
  box-shadow: none !important;
}

/* Color definition for Icons in passive state */
.color-online { color: rgba(52, 211, 153, 0.85); }
.color-danger { color: rgba(248, 113, 113, 0.85); }
.color-primary { color: rgba(96, 165, 250, 0.85); }
.color-warning { color: rgba(251, 191, 36, 0.85); }
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
  font-size: 14px;
}
</style>
