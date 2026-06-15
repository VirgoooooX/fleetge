<template>
  <el-drawer
    :model-value="visible"
    :title="`操作输出 — ${stackName}`"
    direction="rtl"
    size="55%"
    class="terminal-drawer"
    @close="onClose"
  >
    <div class="terminal-container">
      <div class="terminal-viewport" ref="viewportRef">
        <div
          v-for="(line, i) in lines"
          :key="i"
          class="terminal-line"
        >{{ line }}</div>
        <div v-if="status === 'running'" class="terminal-cursor">▊</div>
      </div>

      <div class="terminal-footer" :class="`footer-${status}`">
        <div class="footer-left">
          <el-icon v-if="status === 'running'" class="is-loading"><Loading /></el-icon>
          <el-icon v-else-if="status === 'success'" :size="18"><SuccessFilled /></el-icon>
          <el-icon v-else-if="status === 'error'" :size="18"><WarningFilled /></el-icon>
          <span>{{ message }}</span>
        </div>
        <div class="footer-right">
          <el-button
            v-if="lines.length > 0"
            size="small"
            text
            @click="copyOutput"
          >
            {{ copied ? '已复制' : '复制输出' }}
          </el-button>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from "vue";
import { ElMessage } from "element-plus";
import { Loading, SuccessFilled, WarningFilled } from "@element-plus/icons-vue";

const props = defineProps<{
  visible: boolean;
  stackName: string;
  lines: string[];
  status: "running" | "success" | "error" | "idle";
  message: string;
}>();

const emit = defineEmits<{ close: [] }>();

const viewportRef = ref<HTMLElement | null>(null);
const copied = ref(false);

function onClose() {
  emit("close");
}

// Auto-scroll when lines change
watch(
  () => props.lines.length,
  async () => {
    await nextTick();
    if (viewportRef.value) {
      viewportRef.value.scrollTop = viewportRef.value.scrollHeight;
    }
  }
);

async function copyOutput() {
  try {
    await navigator.clipboard.writeText(props.lines.join("\n"));
    copied.value = true;
    setTimeout(() => { copied.value = false; }, 2000);
  } catch {
    ElMessage.warning("复制失败");
  }
}
</script>

<style scoped>
.terminal-container {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 8px;
}

.terminal-viewport {
  flex: 1;
  overflow-y: auto;
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 12px;
  font-family: "Cascadia Code", "Fira Code", "JetBrains Mono", ui-monospace, monospace;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-all;
}

.terminal-line {
  color: #e6edf3;
  min-height: 1.55em;
}

.terminal-line:first-child {
  margin-top: 0;
}

.terminal-cursor {
  display: inline-block;
  color: #58a6ff;
  animation: blink 1s step-end infinite;
}

@keyframes blink {
  50% { opacity: 0; }
}

/* ── Footer ────────────────────────────────────── */
.terminal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
  min-height: 36px;
}

.footer-left {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.footer-right {
  flex-shrink: 0;
}

.footer-running {
  background: rgba(56, 139, 253, 0.12);
  color: var(--accent-blue);
}

.footer-success {
  background: rgba(46, 160, 67, 0.12);
  color: #3fb950;
}

.footer-error {
  background: rgba(248, 81, 73, 0.12);
  color: #f85149;
}
</style>
