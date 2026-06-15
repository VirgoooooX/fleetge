<template>
  <el-drawer
    :model-value="visible"
    :title="`日志: ${stackName}`"
    direction="rtl"
    size="50%"
    @close="$emit('close')"
  >
    <div class="log-container">
      <div class="log-toolbar">
        <el-button size="small" @click="loadLogs" :loading="loading">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
        <el-input-number
          v-model="tail"
          :min="50"
          :max="5000"
          :step="100"
          size="small"
          style="width: 120px"
        />
        <span class="log-hint">行</span>
      </div>
      <div class="log-content" ref="logContent">
        <div v-if="loading" class="log-loading">
          <el-icon class="is-loading"><Loading /></el-icon> 加载中...
        </div>
        <pre v-else-if="logs" class="log-text">{{ logs }}</pre>
        <el-empty v-else description="无日志" />
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from "vue";
import { Refresh, Loading } from "@element-plus/icons-vue";
import { streamSse } from "@/api/sse";

const props = defineProps<{
  visible: boolean;
  hostId: string;
  stackName: string;
}>();

defineEmits<{ close: [] }>();

const loading = ref(false);
const logs = ref("");
const tail = ref(200);
const logContent = ref<HTMLElement | null>(null);
let logStreamController: AbortController | null = null;

const MAX_LOG_CHARS = 300000;

function appendLogLine(text: string) {
  logs.value += `${logs.value ? "\n" : ""}${text}`;
  if (logs.value.length > MAX_LOG_CHARS) {
    logs.value = logs.value.slice(logs.value.length - MAX_LOG_CHARS);
  }
  nextTick(() => {
    if (logContent.value) {
      logContent.value.scrollTop = logContent.value.scrollHeight;
    }
  });
}

function stopLogs() {
  if (logStreamController) {
    logStreamController.abort();
    logStreamController = null;
  }
  loading.value = false;
}

async function loadLogs() {
  stopLogs();
  loading.value = true;
  logs.value = "";

  const controller = new AbortController();
  logStreamController = controller;

  const url =
    `/api/hosts/${encodeURIComponent(props.hostId)}` +
    `/stacks/${encodeURIComponent(props.stackName)}` +
    `/logs/stream?tail=${encodeURIComponent(String(tail.value))}`;

  void streamSse({
    url,
    signal: controller.signal,
    onEvent: (ev) => {
      if (ev.event === "ready") {
        loading.value = false;
        return;
      }
      if (ev.event === "line") {
        loading.value = false;
        const service = ev.data?.service;
        const text = ev.data?.text ?? "";
        appendLogLine(service ? `[${service}] ${text}` : text);
        return;
      }
      if (ev.event === "error") {
        loading.value = false;
        appendLogLine(`Error: ${ev.data?.message || "log stream failed"}`);
        return;
      }
      if (ev.event === "complete") {
        loading.value = false;
        appendLogLine(ev.data?.message || "Log stream ended.");
      }
    },
  })
    .catch((e: any) => {
      if (controller.signal.aborted) return;
      logs.value = `Failed to stream logs: ${e.message}`;
    })
    .finally(() => {
      if (logStreamController === controller) {
        logStreamController = null;
      }
      loading.value = false;
    });
}

watch(
  () => props.visible,
  (v) => {
    if (v) {
      loadLogs();
    } else {
      stopLogs();
    }
  },
  { immediate: true }
);

onUnmounted(() => {
  stopLogs();
});
</script>

<style scoped>
.log-container {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.log-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.log-hint {
  font-size: 12px;
  color: var(--text-secondary);
}
.log-content {
  flex: 1;
  overflow: auto;
  background: #1e1e1e;
  border-radius: 4px;
  padding: 12px;
}
.log-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #ccc;
  padding: 16px;
}
.log-text {
  margin: 0;
  font-family: "Cascadia Code", "Fira Code", monospace;
  font-size: 12px;
  line-height: 1.5;
  color: #d4d4d4;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
