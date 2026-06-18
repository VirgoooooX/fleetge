<template>
  <el-drawer
    :model-value="visible"
    :size="drawerSize"
    class="compose-drawer"
    :with-header="false"
    @close="$emit('close')"
  >
    <!-- Drag handle -->
    <div class="compose-drawer__resize-handle" @mousedown="startDrag" />
    <div class="compose-editor">
      <header class="compose-editor__header">
        <div>
          <div class="compose-editor__kicker">{{ t('compose.kicker') }}</div>
          <h2 v-if="!createMode">{{ stackName }}</h2>
          <el-input
            v-else
            v-model="newStackName"
            class="stack-name-input"
            :placeholder="t('compose.stackNamePlaceholder')"
            maxlength="64"
            clearable
          />
          <p>{{ composeFileName }}</p>
          <p v-if="managed" class="compose-editor__managed">{{ t('compose.managedByStackService') }}</p>
        </div>
        <div class="compose-editor__actions">
          <el-button class="ui-button ui-button--muted" :disabled="loading || saving" @click="$emit('close')">
            {{ t('compose.close') }}
          </el-button>
          <el-button
            class="ui-button"
            :loading="saving === 'save'"
            :disabled="!canSubmit || loading || !!saving"
            @click="save(false)"
          >
            {{ t('compose.saveDraft') }}
          </el-button>
          <el-button
            class="ui-button ui-button--primary"
            type="primary"
            :loading="saving === 'deploy'"
            :disabled="!canSubmit || loading || !!saving"
            @click="save(true)"
          >
            {{ t('compose.saveAndDeploy') }}
          </el-button>
        </div>
      </header>

      <el-alert
        v-if="!canSubmit && !loading"
        :title="emptyAlert"
        type="warning"
        show-icon
        :closable="false"
        class="compose-alert"
      />

      <div v-if="loading" class="compose-loading">
        <el-icon class="is-loading" :size="28"><Loading /></el-icon>
      </div>

      <el-tabs
        v-else-if="saving !== 'deploy'"
        v-model="activeTab"
        class="compose-tabs"
      >
        <el-tab-pane :label="composeFileName" name="yaml">
          <MonacoEditor
            v-model="composeYaml"
            language="yaml"
            height="520px"
            :readonly="!canUseEditor"
            :disabled="!!saving"
          />
        </el-tab-pane>
        <el-tab-pane label=".env" name="env">
          <MonacoEditor
            v-model="composeEnv"
            language="ini"
            height="400px"
            :readonly="!canUseEditor"
            :disabled="!!saving"
          />
        </el-tab-pane>
      </el-tabs>

      <div v-if="saving === 'deploy'" class="deploy-terminal">
        <div class="deploy-terminal-header">
          <span>{{ t('compose.deployOutput') }}</span>
          <el-button
            v-if="deployChunks.length > 0"
            class="ui-button ui-button--compact"
            size="small"
            text
            :icon="DocumentCopy"
            @click="copyDeployOutput"
          >
            {{ deployCopied ? t('terminal.copied') : t('terminal.copyOutput') }}
          </el-button>
        </div>
        <div class="deploy-terminal-viewport" ref="deployTerminalRef" />
      </div>

      <div v-if="operationStatus" class="compose-operation-status" :class="`op-${operationStatus.status}`">
        <el-icon v-if="operationStatus.status === 'running'" class="is-loading"><Loading /></el-icon>
        <el-icon v-else-if="operationStatus.status === 'success'"><SuccessFilled /></el-icon>
        <el-icon v-else-if="operationStatus.status === 'error'"><WarningFilled /></el-icon>
        <span class="op-message">{{ operationStatus.message }}</span>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onUnmounted } from "vue";
import MonacoEditor from "@/components/MonacoEditor.vue";
import { ElMessage } from "element-plus";
import { useI18n } from "vue-i18n";
import { Loading, SuccessFilled, WarningFilled, DocumentCopy } from "@element-plus/icons-vue";
import { apiClient } from "@/api/client";
import { streamSse } from "@/api/sse";
import { useConfirm } from "@/composables/useConfirm";
import { Terminal as XtermTerminal, type ITheme } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

const props = defineProps<{
  visible: boolean;
  hostId: string;
  stackName: string;
  createMode?: boolean;
}>();

const emit = defineEmits<{ close: []; saved: [] }>();

const { t } = useI18n();
const { confirm } = useConfirm();

// ── Draggable drawer width ──────────────────────────────────────────────────
const STORAGE_KEY = "compose-drawer-width-pct";
const MIN_PX = 360;
const MAX_VW = 0.9;
const DEFAULT_PCT = 52;

function clampPct(pct: number) {
  const minPct = (MIN_PX / window.innerWidth) * 100;
  const maxPct = MAX_VW * 100;
  return Math.min(maxPct, Math.max(minPct, pct));
}

const drawerWidthPct = ref<number>(
  (() => {
    try {
      const stored = parseFloat(localStorage.getItem(STORAGE_KEY) || "");
      return isNaN(stored) ? DEFAULT_PCT : clampPct(stored);
    } catch {
      return DEFAULT_PCT;
    }
  })()
);

const drawerSize = computed(() => `${drawerWidthPct.value}%`);

function startDrag(e: MouseEvent) {
  e.preventDefault();
  const startX = e.clientX;
  const startPct = drawerWidthPct.value;

  function onMove(ev: MouseEvent) {
    // Drawer opens from the right, so dragging left = wider
    const deltaPx = startX - ev.clientX;
    const deltaPct = (deltaPx / window.innerWidth) * 100;
    drawerWidthPct.value = clampPct(startPct + deltaPct);
  }

  function onUp() {
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
    try { localStorage.setItem(STORAGE_KEY, String(drawerWidthPct.value)); } catch {}
  }

  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
}
// ────────────────────────────────────────────────────────────────────────────

const loading = ref(false);
const saving = ref<"save" | "deploy" | null>(null);
const activeTab = ref("yaml");
const composeYaml = ref("");
const composeEnv = ref("");
const composeFileName = ref("compose.yaml");
const newStackName = ref("");
const managed = ref(false);
const operationStatus = ref<{
  status: string;
  message: string;
  logTail?: string;
} | null>(null);

const deployChunks = ref<string[]>([]);
const deployStreamActive = ref(false);
const deployCopied = ref(false);
const deployTerminalRef = ref<HTMLElement | null>(null);
let deployTerminal: XtermTerminal | null = null;
let deployFitAddon: FitAddon | null = null;
let deployRenderedChunkCount = 0;
let deployResizeObserver: ResizeObserver | null = null;
let deployThemeObserver: MutationObserver | null = null;

const darkDeployTheme: ITheme = {
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

const lightDeployTheme: ITheme = {
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

const DEFAULT_COMPOSE_YAML = `services:
  app:
    image: nginx:latest
    restart: unless-stopped
`;

const createMode = computed(() => !!props.createMode);
const targetStackName = computed(() =>
  createMode.value ? newStackName.value.trim() : props.stackName
);
const hasValidStackName = computed(() =>
  !createMode.value || /^[a-z0-9_-]+$/.test(targetStackName.value)
);
const canUseEditor = computed(() => createMode.value || !!composeYaml.value.trim());
const canSubmit = computed(() =>
  !!composeYaml.value.trim() && !!targetStackName.value && hasValidStackName.value
);
const emptyAlert = computed(() =>
  !targetStackName.value
    ? t("compose.emptyNameAlert")
    : !hasValidStackName.value
      ? t("compose.invalidNameAlert")
      : composeYaml.value.trim()
        ? ""
        : createMode.value
          ? t("compose.emptyYamlAlert")
          : t("compose.noComposeAlert")
);

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      operationStatus.value = null;
      deployChunks.value = [];
      deployStreamActive.value = false;
      if (createMode.value) {
        initializeCreateCompose();
      } else {
        fetchCompose();
      }
    }
  },
  { immediate: true }
);

watch(
  () => deployChunks.value,
  () => {
    deployRenderedChunkCount = 0;
    deployTerminal?.clear();
    deployTerminal?.reset();
    writeDeployChunks(0, true);
  }
);

watch(
  () => deployChunks.value.length,
  () => {
    writeDeployChunks(deployRenderedChunkCount);
  }
);

function initializeCreateCompose() {
  loading.value = false;
  activeTab.value = "yaml";
  newStackName.value = "";
  composeYaml.value = DEFAULT_COMPOSE_YAML;
  composeEnv.value = "";
  composeFileName.value = "compose.yaml";
  managed.value = true;
}

async function fetchCompose() {
  loading.value = true;
  activeTab.value = "yaml";
  try {
    const res = await apiClient.get(
      `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(props.stackName)}/compose`
    );
    composeYaml.value = res.data.compose_yaml || "";
    composeEnv.value = res.data.compose_env || "";
    composeFileName.value = res.data.compose_file_name || "compose.yaml";
    managed.value = !!res.data.is_managed_by_agent;
  } catch (e: any) {
    managed.value = false;
    composeYaml.value = "";
    composeEnv.value = "";
    ElMessage.error(t("compose.readFailed", { detail: e.response?.data?.detail || e.message }));
  } finally {
    loading.value = false;
  }
}

async function save(deploy: boolean) {
  const stackNameForRequest = targetStackName.value;
  if (!stackNameForRequest) {
    ElMessage.error(t("compose.nameRequired"));
    return;
  }
  if (!hasValidStackName.value) {
    ElMessage.error(t("compose.nameInvalid"));
    return;
  }
  if (!composeYaml.value.trim()) {
    ElMessage.error(t("compose.emptyYamlAlert"));
    return;
  }

  const actionLabel = createMode.value ? t("compose.createAction") : t("compose.saveAction");
  try {
    await confirm(
      deploy
        ? t("compose.confirmDeploy", { action: actionLabel, name: stackNameForRequest })
        : t("compose.confirmSave", { action: actionLabel, name: stackNameForRequest }),
      deploy
        ? t("compose.confirmDeployTitle", { action: actionLabel })
        : t("compose.confirmSaveTitle", { action: actionLabel }),
      {
        tone: deploy ? "warning" : "info",
        confirmButtonText: deploy
          ? t("compose.confirmDeployTitle", { action: actionLabel })
          : actionLabel,
        cancelButtonText: t("compose.cancel"),
        confirmButtonClass: "pg-confirm-btn",
      }
    );
  } catch {
    return;
  }

  if (!deploy) {
    saving.value = "save";

    operationStatus.value = {
      status: "running",
      message: t("compose.saving"),
    };

    try {
      const url = `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(stackNameForRequest)}/compose`;
      const res = await apiClient.request({
        method: "put",
        url,
        data: {
          compose_yaml: composeYaml.value,
          compose_env: composeEnv.value,
          compose_file_name: composeFileName.value,
          is_add: createMode.value,
        },
        timeout: 60000,
      });

      operationStatus.value = {
        status: "success",
        message: createMode.value ? t("compose.draftCreated") : t("compose.draftSaved"),
        logTail: res.data?.log_tail || undefined,
      };

      ElMessage.success(createMode.value ? t("compose.draftCreated") : t("compose.draftSaved"));
      emit("saved");
    } catch (e: any) {
      const detail = e.response?.data?.detail || e.message;

      operationStatus.value = {
        status: "error",
        message: t("compose.saveFailed", { detail }),
        logTail: e.response?.data?.log_tail || undefined,
      };

      ElMessage.error(t("compose.saveFailed", { detail }));
    } finally {
      saving.value = null;
    }
    return;
  }

  saving.value = "deploy";
  deployChunks.value = [];
  deployStreamActive.value = true;
  nextTick(() => initDeployTerminal());

  operationStatus.value = {
    status: "running",
    message: t("compose.deploying"),
  };

  const url = `/api/hosts/${props.hostId}/stacks/${encodeURIComponent(stackNameForRequest)}/compose/deploy`;
  let completed = false;

  try {
    await streamSse({
      url,
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      timeoutMs: 300000,
      body: JSON.stringify({
        compose_yaml: composeYaml.value,
        compose_env: composeEnv.value,
        compose_file_name: composeFileName.value,
        is_add: createMode.value,
      }),
      onTimeout: () => {
        completed = true;
        deployStreamActive.value = false;
        operationStatus.value = {
          status: "error",
          message: t("compose.deployTimeout"),
        };
        ElMessage.warning(operationStatus.value.message);
      },
      onEvent: (ev) => {
        if (ev.event === "chunk") {
          deployChunks.value.push(ev.data?.raw ?? ev.rawData);
        } else if (ev.event === "line") {
          // Backward compatibility for old SSE protocol
          deployChunks.value.push(ev.data?.text ?? ev.rawData);
        } else if (ev.event === "complete") {
          completed = true;
          deployStreamActive.value = false;
          const data = ev.data || {};
          const success = data.status === "success";

          operationStatus.value = {
            status: success ? "success" : "error",
            message: data.message || (success ? t("compose.deploySuccess") : t("compose.deployFailed", { detail: "" })),
          };

          if (success) {
            ElMessage.success(createMode.value ? t("compose.createdAndDeployed") : t("compose.deployedAndSaved"));
            emit("saved");
          } else {
            ElMessage.error(t("compose.deployFailed", { detail: data.message || t("compose.unknownError") }));
          }
        } else if (ev.event === "error") {
          completed = true;
          deployStreamActive.value = false;
          const data = ev.data || {};
          operationStatus.value = {
            status: "error",
            message: t("compose.deployFailed", { detail: data.message || t("compose.unknownError") }),
          };
          ElMessage.error(operationStatus.value.message);
        }
      },
    });

    if (!completed && deployStreamActive.value) {
      deployStreamActive.value = false;
      operationStatus.value = {
        status: "success",
        message: t("compose.deployCompleted"),
      };
      ElMessage.success(createMode.value ? t("compose.createdAndDeployed") : t("compose.deployedAndSaved"));
      emit("saved");
    }
  } catch (e: any) {
    if (completed) return;
    deployStreamActive.value = false;
    const detail = e.message || t("compose.unknownError");
    operationStatus.value = {
      status: "error",
      message: t("compose.deployFailed", { detail }),
    };
    ElMessage.error(t("compose.deployFailed", { detail }));
  } finally {
    saving.value = null;
  }
}

watch(
  () => saving.value,
  (newVal, oldVal) => {
    if (newVal !== "deploy" && oldVal === "deploy") {
      disposeDeployTerminal();
    }
  }
);

onUnmounted(() => {
  disposeDeployTerminal();
});

function currentDeployTheme(): ITheme {
  return document.documentElement.dataset.theme === "light"
    ? lightDeployTheme
    : darkDeployTheme;
}

function applyDeployTheme() {
  if (!deployTerminal) return;
  deployTerminal.options.theme = currentDeployTheme();
}

function initDeployTerminal() {
  if (deployTerminal || !deployTerminalRef.value) return;

  deployTerminal = new XtermTerminal({
    convertEol: true,
    cursorBlink: true,
    cursorStyle: "bar",
    fontFamily: "'JetBrains Mono', 'Cascadia Code', Consolas, monospace",
    fontSize: 12,
    lineHeight: 1.55,
    scrollback: 2000,
    theme: currentDeployTheme(),
  });

  deployFitAddon = new FitAddon();
  deployTerminal.loadAddon(deployFitAddon);

  deployTerminal.open(deployTerminalRef.value);
  deployRenderedChunkCount = 0;
  writeDeployChunks(0, true);
  nextTick(() => deployFitAddon?.fit());

  deployResizeObserver = new ResizeObserver(() => deployFitAddon?.fit());
  deployResizeObserver.observe(deployTerminalRef.value);

  deployThemeObserver = new MutationObserver(() => applyDeployTheme());
  deployThemeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme", "class"],
  });
}

function disposeDeployTerminal() {
  deployResizeObserver?.disconnect();
  deployResizeObserver = null;
  deployThemeObserver?.disconnect();
  deployThemeObserver = null;
  deployTerminal?.dispose();
  deployTerminal = null;
  deployFitAddon = null;
  deployRenderedChunkCount = 0;
}

function writeDeployChunks(startIndex: number, force = false) {
  if (!deployTerminal) return;

  if (deployChunks.value.length === 0) {
    deployRenderedChunkCount = 0;
    if (force) {
      deployTerminal.clear();
    }
    return;
  }

  if (startIndex === 0 && deployRenderedChunkCount === 0) {
    deployTerminal.clear();
  }

  for (let i = startIndex; i < deployChunks.value.length; i++) {
    deployTerminal.write(deployChunks.value[i]);
  }
  deployRenderedChunkCount = deployChunks.value.length;
  deployFitAddon?.fit();
}

function getDeployTerminalPlainText(): string {
  if (!deployTerminal) return "";
  const buffer = deployTerminal.buffer.active;
  const lines: string[] = [];
  for (let i = 0; i < buffer.length; i++) {
    const line = buffer.getLine(i);
    if (line) lines.push(line.translateToString().trimEnd());
  }
  return lines.join("\n").trimEnd();
}

async function copyDeployOutput() {
  try {
    await navigator.clipboard.writeText(getDeployTerminalPlainText());
    deployCopied.value = true;
    setTimeout(() => { deployCopied.value = false; }, 2000);
  } catch {
    ElMessage.warning(t("terminal.copyFailed"));
  }
}
</script>

<style scoped>
/* ── Drag handle ── */
.compose-drawer__resize-handle {
  position: absolute;
  left: 0;
  top: 0;
  width: 5px;
  height: 100%;
  cursor: ew-resize;
  z-index: 10;
  background: transparent;
  transition: background 0.15s;
}
.compose-drawer__resize-handle:hover,
.compose-drawer__resize-handle:active {
  background: var(--accent-blue, #3b82f6);
  opacity: 0.35;
}

.compose-editor {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 100%;
}

.compose-editor__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: 14px;
}

.compose-editor__kicker {
  color: var(--accent-blue);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.compose-editor h2 {
  margin: 4px 0 0;
  color: var(--text-primary);
  font-size: 20px;
}

.stack-name-input {
  width: min(360px, 62vw);
  margin-top: 4px;
}

.stack-name-input :deep(.el-input__wrapper) {
  background: var(--surface-base);
  border-radius: 6px;
  box-shadow: 0 0 0 1px var(--border-subtle) inset;
}

.compose-editor p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 12px;
}

.compose-editor__managed {
  color: var(--success) !important;
  font-family: var(--font-mono);
  font-size: 11px;
  margin-top: 4px;
}

.compose-editor__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.compose-alert {
  margin: 0;
}

.compose-loading {
  display: grid;
  place-items: center;
  min-height: 300px;
}

.compose-tabs {
  min-height: 0;
}

/* Monaco editor handles its own typography */

.deploy-terminal {
  display: flex;
  flex-direction: column;
  max-height: 60vh;
  border: 1px solid #30363d;
  border-radius: 6px;
  overflow: hidden;
}

.deploy-terminal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 12px;
  background: #161b22;
  color: #8b949e;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-bottom: 1px solid #30363d;
}

.deploy-terminal-viewport {
  flex: 1;
  min-height: 260px;
  height: 50vh;
  padding: 12px;
  overflow: hidden;
  background: #0d1117;
}

.deploy-terminal-viewport :deep(.xterm) {
  height: 100%;
}

.deploy-terminal-viewport :deep(.xterm-viewport) {
  background: #0d1117 !important;
}

:global([data-theme="light"] .deploy-terminal) {
  border-color: rgba(60, 72, 88, 0.16);
}

:global([data-theme="light"] .deploy-terminal-header) {
  background: #eef2f7;
  color: #64748b;
  border-bottom-color: rgba(60, 72, 88, 0.16);
}

:global([data-theme="light"] .deploy-terminal-viewport) {
  background: #f8fafc;
}

:global([data-theme="light"] .deploy-terminal-viewport) :deep(.xterm-viewport) {
  background: #f8fafc !important;
}

.compose-operation-status {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.4;
}
.compose-operation-status.op-running {
  background: rgba(59, 130, 246, 0.10);
  color: var(--accent-blue);
}
.compose-operation-status.op-success {
  background: rgba(22, 163, 74, 0.10);
  color: var(--success);
}
.compose-operation-status.op-error {
  background: rgba(220, 38, 38, 0.10);
  color: var(--danger);
}
.op-message {
  flex: 1;
  min-width: 0;
}

@media (max-width: 900px) {
  .compose-editor__header {
    flex-direction: column;
  }
}
</style>
