<template>
  <section class="operation-terminal" :class="[`is-${status}`, { compact }]">
    <div class="terminal-head">
      <div class="terminal-title">
        <span class="terminal-mark">[_]</span>
        <strong>{{ actionTitle }}</strong>
        <span class="stack-name">{{ stackName }}</span>
      </div>

      <div class="terminal-tools">
        <span v-if="status !== 'running'" class="terminal-state" :class="`state-${status}`">
          <el-icon v-if="status === 'success'"><SuccessFilled /></el-icon>
          <el-icon v-else-if="status === 'error'"><WarningFilled /></el-icon>
          {{ statusLabel }}
        </span>
        <el-button v-if="lines.length > 0" size="small" text @click.stop="copyOutput">
          {{ copied ? "已复制" : "复制" }}
        </el-button>
        <el-button size="small" text aria-label="关闭操作输出" @click.stop="$emit('close')">
          <el-icon><Close /></el-icon>
        </el-button>
      </div>
    </div>

    <div ref="terminalRef" class="terminal-surface" />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { Close, SuccessFilled, WarningFilled } from "@element-plus/icons-vue";
import { Terminal as XtermTerminal, type ITheme } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

const props = withDefaults(defineProps<{
  stackName: string;
  action?: string;
  lines: string[];
  status: "running" | "success" | "error" | "idle";
  message: string;
  compact?: boolean;
}>(), {
  action: "",
  compact: false,
});

defineEmits<{ close: [] }>();

const terminalRef = ref<HTMLElement | null>(null);
const copied = ref(false);
let terminal: XtermTerminal | null = null;
let fitAddon: FitAddon | null = null;
let renderedLineCount = 0;
let resizeObserver: ResizeObserver | null = null;
let themeObserver: MutationObserver | null = null;

const darkTerminalTheme: ITheme = {
  background: "#000000",
  foreground: "#f8fbff",
  cursor: "#f8fbff",
  black: "#000000",
  blue: "#3b82f6",
  cyan: "#22d3ee",
  green: "#22c55e",
  red: "#ef4444",
  yellow: "#f59e0b",
  white: "#f8fbff",
};

const lightTerminalTheme: ITheme = {
  background: "#f8fafc",
  foreground: "#0f172a",
  cursor: "#0f172a",
  black: "#0f172a",
  blue: "#2563eb",
  cyan: "#0891b2",
  green: "#16a34a",
  red: "#dc2626",
  yellow: "#d97706",
  white: "#f8fafc",
};

const actionTitle = computed(() => {
  const labels: Record<string, string> = {
    start: "Starting",
    stop: "Stopping",
    restart: "Restarting",
    update: "Updating",
  };
  return labels[props.action] || "Operation";
});

const statusLabel = computed(() => {
  if (props.status === "success") return "完成";
  if (props.status === "error") return "失败";
  if (props.status === "idle") return "结束";
  return "";
});

onMounted(() => {
  terminal = new XtermTerminal({
    convertEol: true,
    cursorBlink: false,
    fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
    fontSize: 13,
    lineHeight: 1.2,
    rows: props.compact ? 7 : 10,
    scrollback: 800,
    theme: currentTerminalTheme(),
  });

  fitAddon = new FitAddon();
  terminal.loadAddon(fitAddon);

  if (terminalRef.value) {
    terminal.open(terminalRef.value);
    flushLines(true);
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
  () => [props.stackName, props.action],
  () => {
    renderedLineCount = 0;
    terminal?.clear();
    flushLines(true);
  },
);

watch(
  () => props.lines.length,
  () => {
    if (props.lines.length < renderedLineCount) {
      renderedLineCount = 0;
      terminal?.clear();
    }
    flushLines();
  },
  { flush: "post" },
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

function flushLines(force = false) {
  if (!terminal) return;
  if (force && renderedLineCount === 0 && props.lines.length === 0) {
    terminal.write("\x1b[2mWaiting for Dockge output...\x1b[0m\r\n");
    return;
  }

  if (renderedLineCount === 0) {
    terminal.clear();
  }

  const pending = props.lines.slice(renderedLineCount);
  for (const line of pending) {
    terminal.write(normalizeTerminalLine(line));
  }
  renderedLineCount = props.lines.length;
  fitTerminal();
}

function normalizeTerminalLine(line: string): string {
  const text = line.endsWith("\n") || line.endsWith("\r") ? line : `${line}\r\n`;
  return text.replace(/\n/g, "\r\n");
}

async function copyOutput() {
  try {
    await navigator.clipboard.writeText(props.lines.join("\n"));
    copied.value = true;
    setTimeout(() => {
      copied.value = false;
    }, 1800);
  } catch {
    ElMessage.warning("复制失败");
  }
}
</script>

<style scoped>
.operation-terminal {
  overflow: hidden;
  border: 1px solid rgba(34, 197, 94, 0.74);
  border-radius: 7px;
  background: #000000;
  box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.12);
}

:global([data-theme="light"] .operation-terminal) {
  background: #f8fafc;
  border-color: rgba(22, 163, 74, 0.42);
  box-shadow: 0 0 0 1px rgba(22, 163, 74, 0.08);
}

.operation-terminal.is-error {
  border-color: rgba(248, 113, 113, 0.86);
  box-shadow: 0 0 0 1px rgba(248, 113, 113, 0.16);
}

:global([data-theme="light"] .operation-terminal.is-error) {
  border-color: rgba(220, 38, 38, 0.46);
  box-shadow: 0 0 0 1px rgba(220, 38, 38, 0.10);
}

.operation-terminal.is-idle {
  border-color: var(--border-strong);
  box-shadow: none;
}

.terminal-head {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 0 14px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.14);
  background: #050914;
}

:global([data-theme="light"] .terminal-head) {
  border-bottom-color: rgba(60, 72, 88, 0.14);
  background: #eef2f7;
}

.terminal-title,
.terminal-tools,
.terminal-state {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.terminal-title {
  gap: 8px;
  color: #f8fbff;
  font-family: var(--font-mono);
  font-size: 12px;
}

:global([data-theme="light"] .terminal-title) {
  color: #0f172a;
}

.terminal-title strong {
  font-weight: 800;
}

.terminal-mark {
  color: #3b82f6;
  font-weight: 900;
}

.stack-name {
  overflow: hidden;
  color: #f8fbff;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global([data-theme="light"] .stack-name) {
  color: #0f172a;
}

.terminal-tools {
  gap: 10px;
}

.terminal-tools :deep(.el-button) {
  min-height: 26px;
  padding: 0 2px !important;
  color: #8aa0b7 !important;
}

:global([data-theme="light"] .terminal-tools) :deep(.el-button) {
  color: #64748b !important;
}

.terminal-state {
  gap: 5px;
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
}

.state-success {
  color: var(--success);
}

.state-error {
  color: var(--danger);
}

.terminal-surface {
  height: 180px;
  padding: 12px 14px;
  background: #000000;
}

:global([data-theme="light"] .terminal-surface) {
  background: #f8fafc;
}

.operation-terminal.compact .terminal-surface {
  height: 142px;
}

.terminal-surface :deep(.xterm) {
  height: 100%;
}

.terminal-surface :deep(.xterm-viewport) {
  background: #000000 !important;
}

:global([data-theme="light"] .terminal-surface) :deep(.xterm-viewport) {
  background: #f8fafc !important;
}

.terminal-surface :deep(.xterm-screen) {
  padding-bottom: 1px;
}

@media (max-width: 720px) {
  .terminal-head {
    grid-template-columns: 1fr;
    padding: 8px 12px;
  }

  .terminal-tools {
    justify-content: space-between;
  }
}
</style>
