<template>
  <section v-if="active" class="settings-section" v-loading="store.loadingHosts">
    <div class="section-heading">
      <div>
        <h3>{{ t("settings.sections.hosts") }}</h3>
        <p>{{ t("settings.hosts.count", { count: store.hosts.length }) }}</p>
      </div>
      <div class="section-actions">
        <el-button type="primary" class="ui-button ui-button--primary" :icon="Plus" @click="openAddHostChoiceDialog">
          {{ t("settings.hosts.add") }}
        </el-button>
      </div>
    </div>

    <div class="table-frame">
      <el-table :data="store.hosts" stripe style="width: 100%" class="host-table">
        <el-table-column :label="t('settings.hosts.col.sort')" prop="sort_order" width="70" align="center" class-name="mobile-hidden" label-class-name="mobile-hidden" />
        <el-table-column :label="t('settings.hosts.col.id')" prop="host_id" width="140" class-name="mobile-hidden" label-class-name="mobile-hidden">
          <template #default="{ row }">
            <span class="host-code-text">{{ row.host_id }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('settings.hosts.col.name')" prop="display_name" width="170" />
        <el-table-column :label="t('settings.hosts.col.url')" min-width="220" prop="agent_url" class-name="mobile-hidden" label-class-name="mobile-hidden">
          <template #default="{ row }">
            <span class="host-code-text">{{ row.agent_url || "-" }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('settings.hosts.col.status')" prop="enabled" width="90" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="toggleHostEnabled(row as HostConfigResponse)" :loading="store.updatingHosts.has(row.host_id)" />
          </template>
        </el-table-column>
        <el-table-column
          :label="t('settings.hosts.col.appProfiles')"
          width="96"
          align="center"
          class-name="mobile-hidden app-profiles-column"
          label-class-name="mobile-hidden"
          :fixed="isMobile ? false : 'right'"
        >
          <template #default="{ row }">
            <div class="app-profiles-cell">
              <el-tooltip :content="t('settings.hosts.col.manageAppProfiles')" placement="top" :show-after="250">
                <button
                  type="button"
                  class="app-profile-settings-btn"
                  :aria-label="t('settings.hosts.col.manageAppProfiles')"
                  @click="openAppProfilesDialog(row as HostConfigResponse)"
                >
                  <el-icon><Settings /></el-icon>
                  <span>{{ t("settings.hosts.col.appProfilesSetup") }}</span>
                </button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="t('settings.hosts.col.actions')" :width="isMobile ? 150 : 224" align="center" :fixed="isMobile ? false : 'right'">
          <template #default="{ row }">
            <div class="row-operations">
              <el-button size="small" type="success" plain class="host-action-btn host-action-test" :loading="store.testingHosts.has(row.host_id)" @click="testHostConnection(row as HostConfigResponse)">
                <el-icon v-if="isMobile"><Link2 /></el-icon>
                <span v-else>{{ t("settings.hosts.action.test") }}</span>
              </el-button>
              <el-tooltip :content="t('settings.globalEnv.manage')" placement="top">
                <el-button size="small" type="info" plain :icon="FileText" class="host-action-btn host-icon-btn" @click="globalEnvDialog?.open(row as HostConfigResponse)" />
              </el-tooltip>
              <el-button size="small" type="info" plain :icon="Pencil" class="host-action-btn host-icon-btn" :aria-label="t('settings.hosts.edit')" @click="hostEditor?.openEditHostDialog(row as HostConfigResponse)" />
              <el-button size="small" type="danger" plain :icon="Trash2" class="host-action-btn host-icon-btn" :loading="store.deletingHosts.has(row.host_id)" @click="confirmDeleteHost(row as HostConfigResponse)" />
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </section>

  <!-- Choice Modal: 添加主机类型选择 -->
  <el-dialog
    v-model="addHostChoiceVisible"
    :title="t('settings.hosts.addChoiceTitle')"
    width="min(540px, calc(100vw - 28px))"
    class="ui-dialog add-host-choice-dialog"
  >
    <div class="add-host-choice-intro">
      <p>{{ t("settings.hosts.addChoiceSubtitle") }}</p>
    </div>
    <div class="add-host-choice-cards">
      <div
        class="add-host-choice-card choice-card--enrollment"
        tabindex="0"
        role="button"
        @click="chooseAddHostMode('enrollment')"
        @keydown.enter.prevent="chooseAddHostMode('enrollment')"
        @keydown.space.prevent="chooseAddHostMode('enrollment')"
      >
        <div class="choice-card-icon">
          <Rocket :size="24" />
        </div>
        <div class="choice-card-body">
          <h4>{{ t("settings.hosts.modeEnrollmentTitle") }}</h4>
          <p>{{ t("settings.hosts.modeEnrollmentDesc") }}</p>
        </div>
        <ChevronRight class="choice-card-arrow" :size="18" />
      </div>

      <div
        class="add-host-choice-card choice-card--manual"
        tabindex="0"
        role="button"
        @click="chooseAddHostMode('manual')"
        @keydown.enter.prevent="chooseAddHostMode('manual')"
        @keydown.space.prevent="chooseAddHostMode('manual')"
      >
        <div class="choice-card-icon">
          <Server :size="24" />
        </div>
        <div class="choice-card-body">
          <h4>{{ t("settings.hosts.modeManualTitle") }}</h4>
          <p>{{ t("settings.hosts.modeManualDesc") }}</p>
        </div>
        <ChevronRight class="choice-card-arrow" :size="18" />
      </div>
    </div>
  </el-dialog>

  <EnrollmentDialog v-model="enrollmentDialogVisible" />

  <HostEditorDialog ref="hostEditor" />

  <AppProfilesDialog
    v-if="appProfilesDialogVisible && selectedHost"
    :key="selectedHost.host_id"
    v-model="appProfilesDialogVisible"
    :host-id="selectedHost.host_id"
    :host-name="selectedHost.display_name"
    :stack-icons="selectedHost.stack_icons"
    @saved="store.fetchHosts()"
  />

  <GlobalEnvDialog ref="globalEnvDialog" />
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import { ChevronRight, FileText, Link2, Pencil, Plus, Rocket, Server, Settings, Trash2 } from "@lucide/vue";
import { apiErrorMessage } from "@/api/errors";
import { useSettingsStore, type HostConfigResponse } from "@/stores/settings";
import { useConfirm } from "@/composables/useConfirm";
import { useMobile } from "@/composables/useMobile";
import AppProfilesDialog from "@/components/AppProfilesDialog.vue";
import HostEditorDialog from "./HostEditorDialog.vue";
import EnrollmentDialog from "./EnrollmentDialog.vue";
import GlobalEnvDialog from "./GlobalEnvDialog.vue";

defineProps<{ active: boolean }>();
const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const store = useSettingsStore();
const { confirm, alert: confirmAlert } = useConfirm();
const { isMobile } = useMobile();

const enrollmentDialogVisible = ref(false);
const addHostChoiceVisible = ref(false);

function openAddHostChoiceDialog() {
  addHostChoiceVisible.value = true;
}

function chooseAddHostMode(mode: "enrollment" | "manual") {
  addHostChoiceVisible.value = false;
  if (mode === "enrollment") {
    enrollmentDialogVisible.value = true;
  } else {
    hostEditor.value?.openCreateHostDialog();
  }
}

const hostEditor = ref<InstanceType<typeof HostEditorDialog>>();

async function toggleHostEnabled(row: HostConfigResponse) {
  try {
    const payload = {
      display_name: row.display_name,
      enabled: row.enabled,
      sort_order: row.sort_order,
      traffic_billing_day: row.traffic_billing_day,
      agent_url: row.agent_url,
      agent_token: null,
    };
    await store.updateHost(row.host_id, payload);
    ElMessage.success(
      t(row.enabled ? "settings.hosts.toggle.enabledSuccess" : "settings.hosts.toggle.disabledSuccess", { name: row.display_name }),
    );
  } catch (err) {
    row.enabled = !row.enabled;
    ElMessage.error(apiErrorMessage(err, t("settings.hosts.toggle.error")));
  }
}

async function confirmDeleteHost(row: HostConfigResponse) {
  try {
    await confirm(
      t("settings.hosts.delete.confirm", { name: row.display_name }),
      t("settings.hosts.delete.title"),
      {
        tone: "danger",
        confirmButtonText: t("stack.action.delete"),
        cancelButtonText: t("stack.confirm.cancel"),
        confirmButtonClass: "pg-confirm-btn",
      },
    );
    await store.deleteHost(row.host_id);
    ElMessage.success(t("settings.hosts.delete.success", { name: row.display_name }));
  } catch (err) {
    if (err !== "cancel") {
      ElMessage.error(apiErrorMessage(err, t("settings.hosts.delete.error")));
    }
  }
}

async function testHostConnection(row: HostConfigResponse) {
  const loadingMsg = ElMessage({
    message: t("settings.hosts.action.testing", { name: row.display_name }),
    duration: 0,
    type: "info",
  });

  const res = await store.testConnection(row.host_id);
  loadingMsg.close();

  if (res.success) {
    confirmAlert(
      t("settings.hosts.test.successDetail", { time: res.response_time_ms, msg: res.message }),
      t("settings.hosts.test.successTitle"),
      { tone: "success", confirmButtonText: t("stack.confirm.ok") },
    );
  } else {
    confirmAlert(
      t("settings.hosts.test.failedDetail", { msg: res.message }),
      t("settings.hosts.test.failedTitle"),
      { tone: "error", confirmButtonText: t("stack.confirm.ok") },
    );
  }
}

const appProfilesDialogVisible = ref(false);
const selectedHost = ref<HostConfigResponse | null>(null);
const globalEnvDialog = ref<InstanceType<typeof GlobalEnvDialog>>();

function openAppProfilesDialog(row: HostConfigResponse) {
  selectedHost.value = row;
  appProfilesDialogVisible.value = true;
}

function openHostEditorFromRoute() {
  const hostId = route.query.host;
  if (route.query.action !== "edit-host" || typeof hostId !== "string") return;
  const host = store.hosts.find((item) => item.host_id === hostId);
  if (!host || !hostEditor.value) return;
  void router.replace({ name: "settings", query: { section: "hosts" } });
  void hostEditor.value.openEditHostDialog(host);
}

watch(
  [() => route.query, () => store.hosts, hostEditor],
  ([query]) => {
    const action = Array.isArray(query.action) ? query.action[0] : query.action;
    if (action === "add-host") {
      openAddHostChoiceDialog();
      void router.replace({ name: "settings", query: { section: "hosts" } });
    }
    openHostEditorFromRoute();
  },
  { immediate: true },
);

onMounted(async () => {
  try {
    await store.fetchHosts();
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t("settings.hosts.fetchError")));
  }
});
</script>

<style scoped src="./settings-section.css"></style>

<style scoped>
.host-table {
  border-radius: 8px;
  overflow: hidden;
}

.host-table :deep(.el-table__cell) {
  padding: 7px 0;
}

.host-table :deep(.cell) {
  padding-left: 8px;
  padding-right: 8px;
}

.unit-text,
.form-help {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.app-profiles-cell {
  display: flex;
  align-items: center;
  justify-content: center;
}

.app-profile-settings-btn {
  height: 28px;
  min-width: 58px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex-shrink: 0;
  border: 1px solid var(--el-border-color);
  border-radius: 7px;
  background: var(--surface-panel);
  color: var(--text-secondary);
  cursor: pointer;
  padding: 0 8px;
  position: relative;
  z-index: 1;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
}

.app-profile-settings-btn:hover {
  background: var(--el-fill-color-light);
  border-color: var(--el-border-color-hover);
  color: var(--text-primary);
}

.app-profile-settings-btn .el-icon {
  width: 14px;
  height: 14px;
  font-size: 14px;
  color: currentColor;
}

.app-profile-settings-btn :deep(svg) {
  width: 14px;
  height: 14px;
  display: block;
}

.row-operations {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  flex-wrap: nowrap;
}

.row-operations :deep(.el-button + .el-button) {
  margin-left: 0;
}

.host-action-btn {
  height: 28px;
}

.host-action-test {
  padding: 0 8px;
}

.host-icon-btn {
  width: 28px;
  padding: 0;
}

.add-host-choice-intro p {
  margin: 0 0 16px;
  color: var(--text-secondary);
  font-size: 13px;
}
.add-host-choice-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.add-host-choice-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px 18px;
  border: 1px solid var(--border-subtle);
  border-radius: 10px;
  background: var(--surface-panel);
  cursor: pointer;
  transition:
    border-color var(--duration-normal, 180ms) var(--ease-standard, ease),
    background-color var(--duration-normal, 180ms) var(--ease-standard, ease),
    box-shadow var(--duration-normal, 180ms) var(--ease-standard, ease),
    transform var(--duration-normal, 180ms) var(--ease-standard, ease);
  user-select: none;
}
.add-host-choice-card:hover,
.add-host-choice-card:focus-visible {
  border-color: var(--accent-blue, #3b82f6);
  background: color-mix(in srgb, var(--accent-blue, #3b82f6) 6%, var(--surface-panel));
  box-shadow: 0 4px 16px rgba(59, 130, 246, 0.12);
  transform: translateY(-1px);
}
.choice-card-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 46px;
  border-radius: 10px;
  flex-shrink: 0;
}
.choice-card--enrollment .choice-card-icon {
  color: #3b82f6;
  background: color-mix(in srgb, #3b82f6 12%, transparent);
}
.choice-card--manual .choice-card-icon {
  color: #10b981;
  background: color-mix(in srgb, #10b981 12%, transparent);
}
.choice-card-body {
  flex: 1;
  min-width: 0;
}
.choice-card-body h4 {
  margin: 0 0 4px;
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 600;
}
.choice-card-body p {
  margin: 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.45;
}
.choice-card-arrow {
  color: var(--text-muted);
  transition: transform 0.2s ease, color 0.2s ease;
}
.add-host-choice-card:hover .choice-card-arrow {
  color: var(--accent-blue, #3b82f6);
  transform: translateX(3px);
}
</style>
