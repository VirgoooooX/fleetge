<template>
  <el-drawer
    :model-value="visible"
    :size="drawerSize"
    class="compose-drawer"
    :class="{ 'is-dragging-drawer': isDragging }"
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
          <p class="compose-editor__meta">{{ composeFileName }}</p>
          <p v-if="managed" class="compose-editor__managed">{{ t('compose.managedByStackService') }}</p>
        </div>
        <div class="compose-editor__actions">
          <el-button class="ui-button ui-button--muted" :disabled="loading || !!saving" @click="$emit('close')">
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
        <el-icon class="is-loading" :size="28"><LoaderCircle /></el-icon>
      </div>



      <el-tabs
        v-if="!loading"
        v-model="activeTab"
        class="compose-tabs"
      >
        <el-tab-pane :label="composeFileName" name="yaml">
          <MonacoEditor
            v-model="composeYaml"
            language="yaml"
            height="100%"
            word-wrap="on"
            :readonly="!canUseEditor"
            :disabled="!!saving"
          />
        </el-tab-pane>
        <el-tab-pane label=".env" name="env">
          <MonacoEditor
            v-model="composeEnv"
            language="ini"
            height="100%"
            word-wrap="on"
            :readonly="!canUseEditor"
            :disabled="!!saving"
          />
        </el-tab-pane>
      </el-tabs>

      <div v-if="operationStatus" class="compose-operation-status" :class="`op-${operationStatus.status}`">
        <el-icon v-if="operationStatus.status === 'running'" class="is-loading"><LoaderCircle /></el-icon>
        <el-icon v-else-if="operationStatus.status === 'success'"><CheckCircle2 /></el-icon>
        <el-icon v-else-if="operationStatus.status === 'error'"><AlertTriangle /></el-icon>
        <span class="op-message">{{ operationStatus.message }}</span>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch, defineAsyncComponent, onUnmounted } from "vue";
const MonacoEditor = defineAsyncComponent(() => import("@/components/MonacoEditor.vue"));
import { ElMessage } from "element-plus";
import { useI18n } from "vue-i18n";
import { AlertTriangle, CheckCircle2, LoaderCircle } from "@lucide/vue";
import { fetchStackCompose, saveStackCompose, stackRequestError, type ComposeDeployPayload } from "@/api/stacks";
export type { ComposeDeployPayload } from "@/api/stacks";
import { useConfirm } from "@/composables/useConfirm";

const props = defineProps<{
  visible: boolean;
  hostId: string;
  stackName: string;
  createMode?: boolean;
}>();

const emit = defineEmits<{
  close: [];
  saved: [payload: ComposeDeployPayload];
  deploy: [payload: ComposeDeployPayload];
}>();

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

// Toggled during drag so we can disable Element's `transition: all 0.3s`
// on .el-drawer (which otherwise animates every width update → "不跟手").
const isDragging = ref(false);
let stopDrag: (() => void) | undefined;

function startDrag(e: MouseEvent) {
  e.preventDefault();
  stopDrag?.();
  const startX = e.clientX;
  const startPct = drawerWidthPct.value;
  let nextPct = startPct;
  let rafId: number | null = null;

  // Disable the drawer's width transition so width tracks the pointer instantly
  isDragging.value = true;

  function flush() {
    rafId = null;
    drawerWidthPct.value = nextPct;
  }

  function onMove(ev: MouseEvent) {
    // Drawer opens from the right, so dragging left = wider
    const deltaPx = startX - ev.clientX;
    const deltaPct = (deltaPx / window.innerWidth) * 100;
    nextPct = clampPct(startPct + deltaPct);
    // Coalesce mousemove bursts into a single reactive update per animation frame
    if (rafId === null) {
      rafId = requestAnimationFrame(flush);
    }
  }

  function onUp() {
    stopDrag = undefined;
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
    drawerWidthPct.value = nextPct;
    isDragging.value = false;
    document.body.style.removeProperty("cursor");
    document.body.style.removeProperty("user-select");
    window.removeEventListener("mousemove", onMove);
    window.removeEventListener("mouseup", onUp);
    try { localStorage.setItem(STORAGE_KEY, String(drawerWidthPct.value)); } catch {}
  }

  stopDrag = onUp;
  document.body.style.cursor = "ew-resize";
  document.body.style.userSelect = "none";
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
  status: "running" | "success" | "error" | "idle";
  message: string;
  logTail?: string;
} | null>(null);



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

let revision = 0;
let composeRequest: AbortController | null = null;

watch(
  [() => props.visible, () => props.hostId, () => props.stackName, createMode],
  ([visible]) => {
    revision++;
    composeRequest?.abort();
    composeRequest = null;
    loading.value = false;
    saving.value = null;
    operationStatus.value = null;
    if (!visible) {
      stopDrag?.();
      return;
    }
    if (createMode.value) {
      initializeCreateCompose();
    } else {
      void fetchCompose();
    }
  },
  { immediate: true }
);

onUnmounted(() => {
  revision++;
  composeRequest?.abort();
  stopDrag?.();
});

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
  const request = new AbortController();
  const currentRevision = revision;
  composeRequest = request;
  loading.value = true;
  activeTab.value = "yaml";
  managed.value = false;
  composeYaml.value = "";
  composeEnv.value = "";
  composeFileName.value = "compose.yaml";
  try {
    const { data } = await fetchStackCompose(props.hostId, props.stackName, request.signal);
    if (currentRevision !== revision) return;
    composeYaml.value = data.compose_yaml || "";
    composeEnv.value = data.compose_env || "";
    composeFileName.value = data.compose_file_name || "compose.yaml";
    managed.value = !!data.is_managed_by_agent;
  } catch (error) {
    if (currentRevision !== revision) return;
    ElMessage.error(t("compose.readFailed", { detail: stackRequestError(error).detail }));
  } finally {
    if (composeRequest === request && currentRevision === revision) {
      composeRequest = null;
      loading.value = false;
    }
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

  if (saving.value || loading.value) return;
  const requestedHostId = props.hostId;
  const currentRevision = revision;
  const payload: ComposeDeployPayload = {
    stackName: stackNameForRequest,
    composeYaml: composeYaml.value,
    composeEnv: composeEnv.value,
    composeFileName: composeFileName.value,
    isAdd: createMode.value,
  };
  const actionLabel = payload.isAdd ? t("compose.createAction") : t("compose.saveAction");
  saving.value = deploy ? "deploy" : "save";
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
    if (currentRevision === revision) saving.value = null;
    return;
  }
  if (currentRevision !== revision) return;

  if (deploy) {
    saving.value = null;
    emit("deploy", payload);
    emit("close");
    return;
  }

  operationStatus.value = { status: "running", message: t("compose.saving") };
  try {
    const { data } = await saveStackCompose(requestedHostId, payload);
    if (currentRevision !== revision) return;
    const message = payload.isAdd ? t("compose.draftCreated") : t("compose.draftSaved");
    operationStatus.value = { status: "success", message, logTail: data.log_tail ?? undefined };
    ElMessage.success(message);
    emit("saved", payload);
  } catch (error) {
    if (currentRevision !== revision) return;
    const { detail, logTail } = stackRequestError(error);
    const message = t("compose.saveFailed", { detail });
    operationStatus.value = { status: "error", message, logTail };
    ElMessage.error(message);
  } finally {
    if (currentRevision === revision) saving.value = null;
  }
}

</script>

<style scoped>
/* Element Plus `.el-drawer` carries `transition: all 0.3s` (drawer.scss),
   which animates EVERY width write during drag → the panel chases the
   pointer instead of tracking it = the "不跟手" feel. We disable it while
   `is-dragging-drawer` is set (see global override in styles/dashboard.css —
   done globally because scoped `:deep()` + forwarded root classes interact
   unpredictably, and a global rule with our own class is unambiguous). */

/* `.compose-drawer` is forwarded onto `.el-drawer` (its root DOM), so this
   descendant combinator reliably reaches the body. */
.compose-drawer :deep(.el-drawer__body) {
  padding: 0;
  overflow: hidden;
}

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
  height: 100%;
  overflow: hidden;
}

.compose-editor__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--border-subtle);
  padding-top: 6px;
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

.compose-editor__meta {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 12px;
}

.compose-editor__managed {
  color: var(--success) !important;
  font-family: var(--font-body);
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
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.compose-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.compose-tabs :deep(.el-tab-pane) {
  height: 100%;
}

/* Monaco editor handles its own typography */

.compose-deploy-dock {
  flex: 0 0 auto;
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
