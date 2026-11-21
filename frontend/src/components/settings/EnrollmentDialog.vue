<template>
  <el-dialog
    v-model="visible"
    :title="t('settings.enrollment.title')"
    width="min(760px, calc(100vw - 28px))"
    class="ui-dialog enrollment-dialog"
  >
    <div class="enrollment-intro">
      <div class="enrollment-intro-icon"><Rocket :size="24" /></div>
      <div>
        <strong>{{ t("settings.enrollment.introTitle") }}</strong>
        <p>{{ t("settings.enrollment.introBody") }}</p>
      </div>
    </div>

    <el-form label-position="top" class="enrollment-form">
      <el-form-item :label="t('settings.enrollment.hostname')">
        <el-input v-model="enrollmentForm.agent_public_host" class="mono-input" placeholder="agent-vps-01.example.com" />
        <div class="form-help">{{ t("settings.enrollment.hostnameHelp") }}</div>
      </el-form-item>
      <el-form-item :label="t('settings.enrollment.dashboardUrl')">
        <el-input v-model="enrollmentForm.dashboard_url" class="mono-input" placeholder="https://fleetge.example.com" />
        <div v-if="enrollmentHttpWarning" class="enrollment-warning">{{ t("settings.enrollment.httpsWarning") }}</div>
      </el-form-item>
      <el-collapse class="enrollment-advanced">
        <el-collapse-item :title="t('settings.enrollment.advanced')" name="advanced">
          <div class="enrollment-option-grid">
            <el-form-item :label="t('settings.enrollment.stackRoot')">
              <el-input v-model="enrollmentForm.stack_root" class="mono-input" />
            </el-form-item>
            <el-form-item :label="t('settings.enrollment.port')">
              <el-input-number v-model="enrollmentForm.agent_port" :min="1" :max="65535" controls-position="right" />
            </el-form-item>
            <el-form-item :label="t('settings.enrollment.image')">
              <el-input v-model="enrollmentForm.agent_image" class="mono-input" :placeholder="t('settings.enrollment.imagePlaceholder')" />
            </el-form-item>
          </div>
        </el-collapse-item>
      </el-collapse>
    </el-form>

    <div v-if="currentInstallCommand" class="install-command-card">
      <div class="install-command-head">
        <span><ShieldCheck :size="16" />{{ t("settings.enrollment.command") }}</span>
        <strong><Clock3 :size="15" />{{ currentInvite ? remainingTime(currentInvite.expires_at) : '--:--' }}</strong>
      </div>
      <code>{{ currentInstallCommand }}</code>
      <div class="install-command-actions">
        <el-button type="primary" @click="copyInstallCommand"><Copy :size="15" />{{ t("settings.enrollment.copy") }}</el-button>
        <el-button v-if="currentInvite && canRevoke(currentInvite.status)" type="danger" plain :loading="revoking.has(currentInvite.invite_id)" @click="revokeInvite(currentInvite.invite_id)">{{ t("settings.enrollment.revoke") }}</el-button>
      </div>
    </div>

    <el-alert
      v-if="listError"
      type="error"
      :title="t('settings.enrollment.errors.load')"
      :closable="false"
      show-icon
    />
    <div v-if="invites.length" class="invite-list">
      <div class="invite-list-title">{{ t("settings.enrollment.recent") }}</div>
      <article v-for="invite in invites.slice(0, 6)" :key="invite.invite_id" class="invite-row">
        <span class="invite-state" :class="invite.status"></span>
        <div>
          <strong>{{ t(`settings.enrollment.status.${invite.status}`) }}</strong>
          <small>{{ invite.agent_public_url || invite.agent_public_host }} · {{ remainingTime(invite.expires_at) }}</small>
          <p v-if="invite.failure_reason">{{ failureReason(invite.failure_reason) }}</p>
        </div>
        <div class="invite-actions">
          <div v-if="['needs_url','failed'].includes(invite.status)" class="invite-retry">
          <el-button size="small" :loading="retrying.has(invite.invite_id)" :disabled="revoking.has(invite.invite_id)" @click="retryInvite(invite.invite_id)">
            <RotateCcw :size="14" />{{ t("settings.enrollment.retry") }}
          </el-button>
          </div>
          <span v-else-if="invite.status === 'verifying'" class="invite-verifying"><LoaderCircle class="spin" :size="14" />{{ t("settings.enrollment.verifying") }}</span>
          <el-button v-if="canRevoke(invite.status)" size="small" type="danger" plain :loading="revoking.has(invite.invite_id)" :disabled="retrying.has(invite.invite_id)" @click="revokeInvite(invite.invite_id)">{{ t("settings.enrollment.revoke") }}</el-button>
        </div>
      </article>
    </div>

    <template #footer>
      <el-button class="ui-button ui-button--muted" @click="visible = false">{{ t("settings.enrollment.close") }}</el-button>
      <el-button class="ui-button ui-button--primary" type="primary" :loading="creatingInvite" @click="generateEnrollmentInvite">{{ t("settings.enrollment.generate") }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { copyText } from "@/utils/clipboard";
import { computed, reactive, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import { Clock3, Copy, LoaderCircle, Rocket, RotateCcw, ShieldCheck } from "@lucide/vue";
import { settingsApi, type EnrollmentInvite, type EnrollmentStatus } from "@/api/settings";
import { apiErrorDetail } from "@/api/errors";
import { useDashboardStore } from "@/stores/dashboard";
import { useSettingsStore } from "@/stores/settings";
import { remainingInviteSeconds } from "@/utils/dateTime";

const visible = defineModel<boolean>({ required: true });
const { t } = useI18n();
const store = useSettingsStore();
const dashboardStore = useDashboardStore();
const invites = ref<EnrollmentInvite[]>([]);
const listError = ref(false);
const creatingInvite = ref(false);
const revoking = reactive(new Set<string>());
const retrying = reactive(new Set<string>());
const enrollmentClock = ref(Date.now());
const install = ref<{ inviteId: string; command: string }>();
let session = 0;
let listRevision = 0;

const enrollmentForm = reactive({
  dashboard_url: "",
  agent_public_host: "",
  stack_root: "/opt/stacks",
  agent_port: 8080 as number | undefined,
  agent_image: "",
});

const currentInvite = computed(() => invites.value.find((item) => item.invite_id === install.value?.inviteId));
const currentInstallCommand = computed(() => {
  const invite = currentInvite.value;
  return invite?.status === "issued" && remainingInviteSeconds(invite.expires_at, enrollmentClock.value)
    ? install.value?.command : undefined;
});

const enrollmentHttpWarning = computed(() => {
  try {
    const url = new URL(enrollmentForm.dashboard_url);
    return url.protocol === "http:" && !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
      && !/^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(url.hostname);
  } catch {
    return false;
  }
});

const errorKeys: Record<string, string> = {
  "dashboard_url must be a valid safe http(s) URL": "dashboardUrl",
  "stack_root must be an absolute Linux path": "stackRoot",
  "agent_public_host must be a concrete public hostname": "hostname",
  "agent_port must be between 1 and 65535": "port",
  "Invalid agent image": "image",
  "This Agent hostname already has an active invitation": "duplicate",
  "Invitation not found": "notFound",
  "Invitation credentials are no longer available": "credentials",
  "Invitation is active": "unavailable",
  "Invitation is expired": "unavailable",
  "Invitation is revoked": "unavailable",
};

const reasonKeys: Record<string, string> = {
  "Invitation expired": "expired",
  "Revoked by administrator": "revoked",
  "Enrollment credentials are incomplete": "credentials",
  "Docker ping failed": "docker",
  "No reachable candidate URL": "unreachable",
  "Agent instance identity did not match": "identity",
  "Agent verification request failed": "request",
  "等待 DNS、HTTPS 或 Agent 可访问": "waiting",
};

function failureReason(reason: string) {
  const key = reasonKeys[reason] || "request";
  return t(`settings.enrollment.reasons.${key}`);
}

function showActionError(error: unknown, fallback: "create" | "revoke" | "retry") {
  const detail = apiErrorDetail(error);
  ElMessage.error(t(`settings.enrollment.errors.${(detail && errorKeys[detail]) || fallback}`));
}

function remainingTime(expiresAt: string) {
  const seconds = remainingInviteSeconds(expiresAt, enrollmentClock.value);
  if (!seconds) return t("settings.enrollment.status.expired");
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

function canRevoke(status: EnrollmentStatus) {
  return status === "issued" || status === "downloaded" || status === "verifying" || status === "needs_url";
}

function replaceInvite(invite: EnrollmentInvite) {
  const { install_command: _command, ...entry } = invite;
  ++listRevision;
  if (invites.value.some((item) => item.invite_id === entry.invite_id)) {
    invites.value = invites.value.map((item) => item.invite_id === entry.invite_id ? entry : item);
  } else {
    invites.value = [entry, ...invites.value];
  }
}

function refreshHosts() {
  void store.fetchHosts().catch((error) => console.error("Failed to refresh enrolled hosts:", error));
  void dashboardStore.fetchHosts();
}

watch(visible, (open, _, onCleanup) => {
  ++session;
  if (!open) {
    install.value = undefined;
    return;
  }
  enrollmentForm.dashboard_url = window.location.origin;
  enrollmentClock.value = Date.now();
  listError.value = false;
  const controller = new AbortController();
  let nextPoll: ReturnType<typeof setTimeout>;
  const clock = setInterval(() => { enrollmentClock.value = Date.now(); }, 1000);

  async function poll() {
    const revision = listRevision;
    try {
      const next = await settingsApi.fetchEnrollmentInvites(controller.signal);
      if (controller.signal.aborted || revision !== listRevision) return;
      const newlyActive = next.some((entry) => entry.status === "active" &&
        invites.value.some((previous) => previous.invite_id === entry.invite_id && previous.status !== "active"));
      invites.value = next;
      listError.value = false;
      if (newlyActive) refreshHosts();
    } catch {
      if (!controller.signal.aborted) listError.value = true;
    } finally {
      if (!controller.signal.aborted) nextPoll = setTimeout(poll, 5000);
    }
  }

  onCleanup(() => {
    controller.abort();
    clearInterval(clock);
    clearTimeout(nextPoll);
    install.value = undefined;
  });
  void poll();
}, { immediate: true, flush: "sync" });

async function generateEnrollmentInvite() {
  if (creatingInvite.value) return;
  const dashboardUrl = enrollmentForm.dashboard_url.trim();
  try {
    const parsed = new URL(dashboardUrl);
    if (!/^https?:\/\//i.test(dashboardUrl) || !parsed.hostname || /['"\\$`\s]/.test(dashboardUrl)) throw new Error();
  } catch {
    ElMessage.error(t("settings.enrollment.errors.dashboardUrl"));
    return;
  }
  if (!/^\/[A-Za-z0-9._~+/@:-]*$/.test(enrollmentForm.stack_root)) {
    ElMessage.error(t("settings.enrollment.errors.stackRoot"));
    return;
  }
  const publicHost = enrollmentForm.agent_public_host.trim().toLowerCase().replace(/\.$/, "");
  if (!/^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(publicHost)) {
    ElMessage.error(t("settings.enrollment.errors.hostname"));
    return;
  }
  const port = enrollmentForm.agent_port;
  if (port === undefined || !Number.isInteger(port) || port < 1 || port > 65535) {
    ElMessage.error(t("settings.enrollment.errors.port"));
    return;
  }
  const requestSession = session;
  creatingInvite.value = true;
  try {
    const invite = await settingsApi.createEnrollmentInvite({
      dashboard_url: dashboardUrl,
      agent_public_host: publicHost,
      stack_root: enrollmentForm.stack_root,
      agent_port: port,
      agent_image: enrollmentForm.agent_image.trim() || undefined,
    });
    replaceInvite(invite);
    if (session === requestSession && visible.value && invite.install_command) {
      install.value = { inviteId: invite.invite_id, command: invite.install_command };
      ElMessage.success(t("settings.enrollment.created"));
    }
  } catch (error) {
    if (session === requestSession && visible.value) showActionError(error, "create");
  } finally {
    creatingInvite.value = false;
  }
}

async function copyInstallCommand() {
  const command = currentInstallCommand.value;
  if (!command) return;
  try {
    await copyText(command);
    ElMessage.success(t("settings.enrollment.copied"));
  } catch {
    ElMessage.error(t("settings.enrollment.errors.copy"));
  }
}

async function revokeInvite(inviteId: string) {
  if (revoking.has(inviteId) || retrying.has(inviteId)) return;
  revoking.add(inviteId);
  try {
    const invite = await settingsApi.revokeEnrollmentInvite(inviteId);
    replaceInvite(invite);
    if (install.value?.inviteId === inviteId) install.value = undefined;
    if (invite.status === "revoked") ElMessage.success(t("settings.enrollment.revoked"));
    else ElMessage.info(t("settings.enrollment.errors.unavailable"));
  } catch (error) {
    showActionError(error, "revoke");
  } finally {
    revoking.delete(inviteId);
  }
}

async function retryInvite(inviteId: string) {
  if (retrying.has(inviteId) || revoking.has(inviteId)) return;
  retrying.add(inviteId);
  try {
    const result = await settingsApi.retryEnrollmentInvite(inviteId);
    const previous = invites.value.find((entry) => entry.invite_id === inviteId);
    if (previous && previous.status !== "active") {
      replaceInvite({ ...previous, status: result.status, failure_reason: null });
    }
    if (result.status === "active") {
      refreshHosts();
      ElMessage.success(t("settings.enrollment.verified"));
    } else {
      ElMessage.info(t("settings.enrollment.verificationRestarted"));
    }
  } catch (error) {
    showActionError(error, "retry");
  } finally {
    retrying.delete(inviteId);
  }
}
</script>

<style scoped>
.enrollment-intro {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px;
  margin-bottom: 18px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel-raised, rgba(59, 130, 246, 0.04));
}

.enrollment-intro-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  color: var(--accent-blue, #3b82f6);
  background: color-mix(in srgb, var(--accent-blue, #3b82f6) 12%, transparent);
  flex-shrink: 0;
}

.enrollment-intro strong {
  display: block;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.enrollment-intro p {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.enrollment-warning {
  margin-top: 6px;
  color: var(--warning, #fbbf24);
  font-size: 11px;
}

.enrollment-advanced {
  margin-top: 18px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  overflow: hidden;
  background: transparent;
}

.enrollment-form :deep(.el-collapse-item__header) {
  padding: 0 16px;
  height: 44px;
  line-height: 44px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  background: var(--surface-panel-raised, rgba(15, 23, 42, 0.03));
  border-bottom: none;
  transition: background 0.2s ease;
}

.enrollment-form :deep(.el-collapse-item__header.is-active) {
  border-bottom: 1px solid var(--border-subtle);
}

.enrollment-form :deep(.el-collapse-item__wrap) {
  background: var(--surface-panel, transparent);
  border-bottom: none;
}

.enrollment-form :deep(.el-collapse-item__content) {
  padding: 16px;
  color: var(--text-primary);
}

.enrollment-option-grid {
  display: grid;
  grid-template-columns: 1fr 140px;
  gap: 14px;
}

.enrollment-option-grid > :last-child {
  grid-column: 1 / -1;
  margin-bottom: 0;
}

.enrollment-form :deep(.el-input-number) {
  width: 100%;
}

.install-command-card {
  margin-top: 16px;
  padding: 14px;
  border: 1px solid color-mix(in srgb, var(--accent-cyan) 28%, var(--border-subtle));
  border-radius: var(--radius-xl, 10px);
  background: var(--terminal-surface);
}

.install-command-head,
.install-command-head span,
.install-command-head strong {
  display: flex;
  align-items: center;
  gap: 7px;
}

.install-command-head {
  justify-content: space-between;
  margin-bottom: 11px;
  color: var(--terminal-text);
  font-size: var(--text-sm);
}

.install-command-head strong {
  color: var(--accent-cyan);
  font-family: var(--font-mono);
}

.install-command-card code {
  display: block;
  max-height: 125px;
  overflow: auto;
  padding: 12px;
  border: 1px solid var(--terminal-border);
  border-radius: var(--radius-md, 7px);
  color: var(--terminal-text);
  background: var(--terminal-bg);
  font: var(--text-xs)/1.65 var(--font-mono);
  word-break: break-all;
}

.install-command-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 11px;
}

.invite-list {
  display: grid;
  gap: 7px;
  margin-top: 18px;
}

.invite-list-title {
  margin-bottom: 2px;
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.invite-row {
  display: grid;
  grid-template-columns: auto minmax(130px, 1fr) minmax(150px, auto);
  align-items: center;
  gap: 10px;
  padding: 10px 11px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg, 8px);
  background: var(--surface-panel-raised);
}

.invite-state {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
}

.invite-state.issued,
.invite-state.downloaded,
.invite-state.verifying {
  background: var(--accent-blue);
  box-shadow: 0 0 9px color-mix(in srgb, var(--accent-blue) 65%, transparent);
}

.invite-state.active {
  background: var(--accent-cyan);
}

.invite-state.needs_url {
  background: var(--warning);
}

.invite-state.failed,
.invite-state.expired,
.invite-state.revoked {
  background: var(--danger);
}

.invite-row strong,
.invite-row small,
.invite-row p {
  display: block;
}

.invite-row strong {
  color: var(--text-primary);
  font-size: var(--text-sm);
}

.invite-row small {
  margin-top: 3px;
  color: var(--text-muted);
  font: var(--text-xs) var(--font-mono);
}

.invite-row p {
  margin: 4px 0 0;
  color: var(--warning);
  font-size: var(--text-xs);
}

.invite-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.invite-retry {
  display: flex;
  gap: 6px;
  min-width: 270px;
}

.invite-verifying {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  color: var(--accent-blue);
  font-size: var(--text-xs);
  white-space: nowrap;
}

@media (max-width: 768px) {
  .enrollment-option-grid,
  .invite-row { grid-template-columns: 1fr; }
  .enrollment-option-grid > :last-child { grid-column: auto; }
  .invite-state { display: none; }
  .invite-retry { min-width: 0; }
}
.form-help {
  margin-top: 6px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.mono-input :deep(.el-input__inner) {
  font-family: var(--font-mono);
}
</style>
