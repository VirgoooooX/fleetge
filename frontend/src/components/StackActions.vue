<template>
  <div class="stack-actions">
    <el-tooltip content="启动" placement="top">
      <el-button
        class="stack-action-button"
        size="small"
        :loading="loading === 'start'"
        :disabled="loading !== null"
        aria-label="启动 Stack"
        @click="confirmAndRun('start', '启动')"
      >
        <el-icon v-if="loading !== 'start'"><VideoPlay /></el-icon>
      </el-button>
    </el-tooltip>
    <el-tooltip content="停止" placement="top">
      <el-button
        class="stack-action-button danger"
        size="small"
        :loading="loading === 'stop'"
        :disabled="loading !== null"
        aria-label="停止 Stack"
        @click="confirmAndRun('stop', '停止')"
      >
        <el-icon v-if="loading !== 'stop'"><VideoPause /></el-icon>
      </el-button>
    </el-tooltip>
    <el-tooltip content="重启" placement="top">
      <el-button
        class="stack-action-button"
        size="small"
        :loading="loading === 'restart'"
        :disabled="loading !== null"
        aria-label="重启 Stack"
        @click="confirmAndRun('restart', '重启')"
      >
        <el-icon v-if="loading !== 'restart'"><Refresh /></el-icon>
      </el-button>
    </el-tooltip>
    <el-tooltip content="更新镜像" placement="top">
      <el-button
        class="stack-action-button update"
        size="small"
        :loading="loading === 'update'"
        :disabled="loading !== null"
        aria-label="更新 Stack"
        @click="confirmAndRun('update', '更新')"
      >
        <el-icon v-if="loading !== 'update'"><Top /></el-icon>
      </el-button>
    </el-tooltip>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { VideoPlay, VideoPause, Refresh, Top } from "@element-plus/icons-vue";
import { streamSse } from "@/api/sse";

export type OperationState = {
  action: string;
  status: "running" | "success" | "error" | "timeout";
  message: string;
  logTail?: string;
  updatedAt: number;
};

export type TerminalLineEvent = {
  action: string;
  line: string;
};

const props = defineProps<{
  hostId: string;
  stackName: string;
}>();

const emit = defineEmits<{
  "operation-start": [payload: OperationState];
  "operation-complete": [payload: OperationState];
  "terminal-line": [payload: TerminalLineEvent];
  refresh: [];
}>();

const loading = ref<string | null>(null);

const actionLabels: Record<string, string> = {
  start: "启动",
  stop: "停止",
  restart: "重启",
  update: "更新",
};

const actionRisks: Record<string, string> = {
  start: "启动已停止的 Stack。",
  stop: "停止 Stack 中的所有容器。正在运行的服务将被中断。",
  restart: "重启 Stack 中的所有容器。短暂中断后自动恢复。",
  update: "拉取最新镜像并重新创建容器。镜像拉取可能耗时。",
};

const actionTimeouts: Record<string, number> = {
  start: 120000,
  stop: 120000,
  restart: 120000,
  update: 240000,
};

// ── Public API ──────────────────────────────────────────────────

async function confirmAndRun(action: string, label: string) {
  try {
    await ElMessageBox.confirm(
      `确定要${label} Stack「${props.stackName}」吗？\n\n${actionRisks[action] || ""}`,
      `${label} Stack`,
      {
        confirmButtonText: "确定",
        cancelButtonText: "取消",
        type: "warning",
      }
    );
  } catch {
    return; // User cancelled
  }

  const startedAt = Date.now();

  const runningState: OperationState = {
    action,
    status: "running",
    message: `${label}中...`,
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
          message: "操作无响应，可能仍在 Dockge 后台执行，请稍后刷新确认。",
          updatedAt: Date.now(),
        };
        emit("operation-complete", timeoutState);
        ElMessage.warning(timeoutState.message);
      },
      onEvent: (ev) => {
        if (ev.event === "line") {
          emit("terminal-line", { action, line: ev.data?.text ?? ev.rawData });
        } else if (ev.event === "complete") {
          completed = true;

          const data = ev.data || {};
          const finalStatus = data.status === "success" ? "success" : "error";
          const completeState: OperationState = {
            action,
            status: finalStatus,
            message: data.message || `${label}${data.status === "success" ? "成功" : "失败"}`,
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
            message: data.message || `${label}失败`,
            updatedAt: Date.now(),
          };
          emit("operation-complete", errorState);
          ElMessage.error(errorState.message);
        }
      },
    });

    // Stream ended without a terminal event — treat as success
    if (!completed) {
      completed = true;
      const successState: OperationState = {
        action,
        status: "success",
        message: `${label}成功`,
        updatedAt: Date.now(),
      };
      emit("operation-complete", successState);
      ElMessage.success(successState.message);
      emit("refresh");
    }
  } catch (e: any) {
    if (completed) return; // already handled by timeout or SSE event
    completed = true;

    const errorDetail = e.message || "未知错误";
    const errorState: OperationState = {
      action,
      status: "error",
      message: `${label}失败：${errorDetail}`,
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
</script>

<style scoped>
.stack-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.stack-action-button {
  width: 28px;
  height: 28px;
  min-height: 28px;
  margin-left: 0 !important;
  padding: 0 !important;
  border: 1px solid var(--border-subtle) !important;
  border-radius: 7px !important;
  background: var(--stack-action-bg, rgba(148, 163, 184, 0.08)) !important;
  color: var(--stack-action-color, var(--text-secondary)) !important;
}

.stack-action-button :deep(.el-icon) {
  font-size: 14px;
}

.stack-action-button:hover,
.stack-action-button:focus-visible {
  border-color: var(--accent-blue) !important;
  background: var(--stack-action-hover-bg, rgba(96, 165, 250, 0.14)) !important;
  color: var(--accent-blue) !important;
}

.stack-action-button.danger:hover,
.stack-action-button.danger:focus-visible {
  border-color: rgba(248, 113, 113, 0.46) !important;
  background: rgba(248, 113, 113, 0.12) !important;
  color: var(--danger) !important;
}

.stack-action-button.update:hover,
.stack-action-button.update:focus-visible {
  border-color: rgba(251, 191, 36, 0.46) !important;
  background: rgba(251, 191, 36, 0.12) !important;
  color: var(--warning) !important;
}
</style>
