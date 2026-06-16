<template>
  <div class="stack-actions">
    <el-tooltip :content="t('stack.action.start')" placement="top">
      <el-button
        class="ui-icon-button ui-icon-button--small"
        size="small"
        :loading="loading === 'start'"
        :disabled="loading !== null"
        :aria-label="t('stack.action.startStack')"
        @click="confirmAndRun('start', t('stack.action.start'))"
      >
        <el-icon v-if="loading !== 'start'"><VideoPlay /></el-icon>
      </el-button>
    </el-tooltip>
    <el-tooltip :content="t('stack.action.stop')" placement="top">
      <el-button
        class="ui-icon-button ui-icon-button--small ui-icon-button--danger"
        size="small"
        :loading="loading === 'stop'"
        :disabled="loading !== null"
        :aria-label="t('stack.action.stopStack')"
        @click="confirmAndRun('stop', t('stack.action.stop'))"
      >
        <el-icon v-if="loading !== 'stop'"><VideoPause /></el-icon>
      </el-button>
    </el-tooltip>
    <el-tooltip :content="t('stack.action.restart')" placement="top">
      <el-button
        class="ui-icon-button ui-icon-button--small"
        size="small"
        :loading="loading === 'restart'"
        :disabled="loading !== null"
        :aria-label="t('stack.action.restartStack')"
        @click="confirmAndRun('restart', t('stack.action.restart'))"
      >
        <el-icon v-if="loading !== 'restart'"><Refresh /></el-icon>
      </el-button>
    </el-tooltip>
    <el-tooltip :content="t('stack.action.update')" placement="top">
      <el-button
        class="ui-icon-button ui-icon-button--small ui-icon-button--warning"
        size="small"
        :loading="loading === 'update'"
        :disabled="loading !== null"
        :aria-label="t('stack.action.updateStack')"
        @click="confirmAndRun('update', t('stack.action.update'))"
      >
        <el-icon v-if="loading !== 'update'"><Top /></el-icon>
      </el-button>
    </el-tooltip>
    <span class="action-separator" />
    <el-tooltip :content="t('stack.action.delete')" placement="top">
      <el-button
        class="ui-icon-button ui-icon-button--small ui-icon-button--danger"
        size="small"
        :loading="deleting"
        :disabled="loading !== null || deleting"
        :aria-label="t('stack.action.deleteStack')"
        @click="confirmAndDelete"
      >
        <el-icon v-if="!deleting"><Delete /></el-icon>
      </el-button>
    </el-tooltip>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { useI18n } from "vue-i18n";
import { VideoPlay, VideoPause, Refresh, Top, Delete } from "@element-plus/icons-vue";
import { streamSse } from "@/api/sse";
import { apiClient } from "@/api/client";

export type OperationState = {
  action: string;
  status: "running" | "success" | "error" | "timeout";
  message: string;
  logTail?: string;
  updatedAt: number;
};

export type TerminalChunkEvent = {
  action: string;
  chunk: string;
};

const props = defineProps<{
  hostId: string;
  stackName: string;
}>();

const emit = defineEmits<{
  "operation-start": [payload: OperationState];
  "operation-complete": [payload: OperationState];
  "terminal-chunk": [payload: TerminalChunkEvent];
  refresh: [];
}>();

const loading = ref<string | null>(null);
const deleting = ref(false);
const { t } = useI18n();

const riskKeys: Record<string, string> = {
  start: "stack.risk.start",
  stop: "stack.risk.stop",
  restart: "stack.risk.restart",
  update: "stack.risk.update",
};

const actionTimeouts: Record<string, number> = {
  start: 120000,
  stop: 120000,
  restart: 120000,
  update: 240000,
};

async function confirmAndRun(action: string, label: string) {
  try {
    await ElMessageBox.confirm(
      t("stack.confirm.message", {
        action: label,
        name: props.stackName,
        risk: t(riskKeys[action]),
      }),
      t("stack.confirm.title", { action: label }),
      {
        confirmButtonText: t("stack.confirm.ok"),
        cancelButtonText: t("stack.confirm.cancel"),
        type: "warning",
      }
    );
  } catch {
    return;
  }

  const startedAt = Date.now();

  const runningState: OperationState = {
    action,
    status: "running",
    message: t("stack.confirm.running", { action: label }),
    updatedAt: startedAt,
  };
  emit("operation-start", runningState);
  loading.value = action;

  let completed = false;
  const timeoutMs = actionTimeouts[action] || 120000;

  try {
    const url = `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(props.stackName)}/${action}`;

    await streamSse({
      url,
      method: "POST",
      timeoutMs,
      onTimeout: () => {
        if (completed) return;
        completed = true;
        const timeoutState: OperationState = {
          action,
          status: "timeout",
          message: t("stack.confirm.timeout"),
          updatedAt: Date.now(),
        };
        emit("operation-complete", timeoutState);
        ElMessage.warning(timeoutState.message);
      },
      onEvent: (ev) => {
        if (ev.event === "chunk") {
          emit("terminal-chunk", { action, chunk: ev.data?.raw ?? ev.rawData });
        } else if (ev.event === "line") {
          // Backward compatibility for old SSE protocol
          emit("terminal-chunk", { action, chunk: ev.data?.text ?? ev.rawData });
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
          emit("operation-complete", completeState);
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
          emit("operation-complete", errorState);
          ElMessage.error(errorState.message);
        }
      },
    });

    if (!completed) {
      completed = true;
      const successState: OperationState = {
        action,
        status: "success",
        message: t("stack.confirm.success", { action: label }),
        updatedAt: Date.now(),
      };
      emit("operation-complete", successState);
      ElMessage.success(successState.message);
      emit("refresh");
    }
  } catch (e: any) {
    if (completed) return;
    completed = true;

    const errorDetail = e.message || t("stack.confirm.unknownError");
    const errorState: OperationState = {
      action,
      status: "error",
      message: t("stack.confirm.failure", { action: label }) + ": " + errorDetail,
      updatedAt: Date.now(),
    };
    emit("operation-complete", errorState);
    ElMessage.error(errorState.message);
  } finally {
    if (loading.value === action) {
      loading.value = null;
    }
  }
}

async function confirmAndDelete() {
  try {
    await ElMessageBox.confirm(
      t("stack.delete.message", { name: props.stackName }),
      t("stack.delete.title"),
      {
        confirmButtonText: t("stack.delete.ok"),
        cancelButtonText: t("stack.confirm.cancel"),
        type: "error",
        confirmButtonClass: "el-button--danger",
      }
    );
  } catch {
    return;
  }

  deleting.value = true;

  try {
    const url = `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(props.stackName)}`;
    await apiClient.delete(url);
    ElMessage.success(t("stack.delete.success", { name: props.stackName }));
    emit("refresh");
  } catch (e: any) {
    const detail = e.response?.data?.detail || e.message || t("stack.confirm.unknownError");
    ElMessage.error(t("stack.delete.failure", { name: props.stackName }) + ": " + detail);
  } finally {
    deleting.value = false;
  }
}
</script>

<style scoped>
.stack-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.action-separator {
  width: 1px;
  height: 18px;
  margin: 0 4px;
  background: var(--border-subtle);
  display: inline-block;
  align-self: center;
}

</style>
