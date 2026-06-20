<template>
  <el-drawer
    :model-value="visible"
    :title="t('terminal.title', { name: stackName })"
    direction="rtl"
    size="55%"
    class="terminal-drawer"
    @close="onClose"
  >
    <div class="terminal-container">
      <div ref="terminalRef" class="terminal-viewport" />

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
            class="ui-button ui-button--compact"
            size="small"
            text
            @click="copyOutput"
          >
            {{ copied ? t('terminal.copied') : t('terminal.copyOutput') }}
          </el-button>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from "vue";
import { ElMessage } from "element-plus";
import { useI18n } from "vue-i18n";
import { Loading, SuccessFilled, WarningFilled } from "@element-plus/icons-vue";
import { Terminal as XtermTerminal, type ITheme } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

const props = defineProps<{
  visible: boolean;
  stackName: string;
  lines: string[];
  status: "running" | "success" | "error" | "idle";
  message: string;
}>();

const emit = defineEmits<{ close: [] }>();

const { t } = useI18n();
const terminalRef = ref<HTMLElement | null>(null);
const copied = ref(false);
let terminal: XtermTerminal | null = null;
let fitAddon: FitAddon | null = null;
let renderedChunkCount = 0;
let resizeObserver: ResizeObserver | null = null;
let themeObserver: MutationObserver | null = null;

const darkTerminalTheme: ITheme = {
  background: "#0d1117",
  foreground: "#e6edf3",
  cursor: "#58a6ff",
  black: "#0d1117",
  blue: "#58a6ff",
  cyan: "#22d3ee",
  green: "#3fb950",
  red: "#f85149",
  yellow: "#f0883e",
  white: "#e6edf3",
};

const lightTerminalTheme: ITheme = {
  background: "#f8fafc",
  foreground: "#0f172a",
  cursor: "#2563eb",
  black: "#0f172a",
  blue: "#2563eb",
  cyan: "#0891b2",
  green: "#16a34a",
  red: "#dc2626",
  yellow: "#d97706",
  white: "#f8fafc",
};

function onClose() {
  emit("close");
}

onMounted(() => {
  terminal = new XtermTerminal({
    convertEol: true,
    cursorBlink: props.status === "running",
    cursorStyle: "bar",
    fontFamily: "'JetBrains Mono', ui-monospace, 'Cascadia Code', 'SFMono-Regular', Menlo, Consolas, 'Liberation Mono', monospace",
    fontSize: 12,
    lineHeight: 1.55,
    scrollback: 2000,
    theme: currentTerminalTheme(),
  });

  fitAddon = new FitAddon();
  terminal.loadAddon(fitAddon);

  if (terminalRef.value) {
    terminal.open(terminalRef.value);
    writeChunks(0, true);
    nextTick(fitTerminal);

    resizeObserver = new ResizeObserver(() => fitTerminal());
    resizeObserver.observe(terminalRef.value);

    themeObserver = new MutationObserver(() => applyTerminalTheme());
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme", "class"],
    });
  }
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  resizeObserver = null;
  themeObserver?.disconnect();
  themeObserver = null;
  terminal?.dispose();
  terminal = null;
  fitAddon = null;
});

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      nextTick(() => fitTerminal());
    }
  }
);

watch(
  () => props.stackName,
  () => {
    renderedChunkCount = 0;
    terminal?.clear();
    terminal?.reset();
    writeChunks(0, true);
  }
);

watch(
  () => props.lines,
  () => {
    renderedChunkCount = 0;
    terminal?.clear();
    terminal?.reset();
    writeChunks(0, true);
  }
);

watch(
  () => props.lines.length,
  () => {
    writeChunks(renderedChunkCount);
  }
);

watch(
  () => props.status,
  (status) => {
    if (terminal) {
      terminal.options.cursorBlink = status === "running";
    }
  }
);

function fitTerminal() {
  try {
    fitAddon?.fit();
  } catch {
    // xterm can throw while the element is being mounted or hidden.
  }
}

function currentTerminalTheme(): ITheme {
  return document.documentElement.dataset.theme === "light"
    ? lightTerminalTheme
    : darkTerminalTheme;
}

function applyTerminalTheme() {
  if (!terminal) return;
  terminal.options.theme = currentTerminalTheme();
}

function writeChunks(startIndex: number, force = false) {
  if (!terminal) return;

  if (props.lines.length === 0) {
    renderedChunkCount = 0;
    if (force) {
      terminal.clear();
    }
    return;
  }

  if (startIndex === 0 && renderedChunkCount === 0) {
    terminal.clear();
  }

  for (let i = startIndex; i < props.lines.length; i++) {
    terminal.write(props.lines[i]);
  }
  renderedChunkCount = props.lines.length;
  fitTerminal();
}

function getTerminalPlainText(): string {
  if (!terminal) return "";
  const buffer = terminal.buffer.active;
  const lines: string[] = [];
  for (let i = 0; i < buffer.length; i++) {
    const line = buffer.getLine(i);
    if (line) lines.push(line.translateToString().trimEnd());
  }
  return lines.join("\n").trimEnd();
}

async function copyOutput() {
  try {
    await navigator.clipboard.writeText(getTerminalPlainText());
    copied.value = true;
    setTimeout(() => { copied.value = false; }, 2000);
  } catch {
    ElMessage.warning(t("terminal.copyFailed"));
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
  overflow: hidden;
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 12px;
  min-height: 0;
}

.terminal-viewport :deep(.xterm) {
  height: 100%;
}

.terminal-viewport :deep(.xterm-viewport) {
  background: #0d1117 !important;
}

:global([data-theme="light"] .terminal-viewport) {
  background: #f8fafc;
  border-color: rgba(60, 72, 88, 0.16);
}

:global([data-theme="light"] .terminal-viewport) :deep(.xterm-viewport) {
  background: #f8fafc !important;
}

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
