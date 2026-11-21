<template>
  <section v-if="active" class="settings-section">
    <div class="section-heading">
      <div>
        <h3>{{ t("settings.sections.audit") }}</h3>
        <p>{{ t("settings.audit.description") }}</p>
      </div>
      <el-button class="ui-button ui-button--muted" :loading="auditLoading" @click="fetchLogs">
        <el-icon><RefreshCw /></el-icon>
        {{ t("shell.refresh") }}
      </el-button>
    </div>

    <div class="table-toolbar">
      <el-input
        v-model="auditSearch"
        class="toolbar-input"
        :placeholder="t('settings.audit.searchPlaceholder')"
        clearable
        :prefix-icon="Search"
      />
      <el-select v-model="auditResultFilter" class="toolbar-select" :placeholder="t('audit.result')">
        <el-option :label="t('apps.chip.all')" value="" />
        <el-option :label="t('audit.success')" value="success" />
        <el-option :label="t('audit.failure')" value="error" />
        <el-option :label="t('audit.partial')" value="partial" />
        <el-option :label="t('audit.uncertain')" value="uncertain" />
        <el-option :label="t('audit.skipped')" value="skipped" />
      </el-select>
      <el-select v-model="auditActionFilter" class="toolbar-select wide" :placeholder="t('audit.action')" clearable>
        <el-option :label="t('apps.chip.all')" value="" />
        <el-option
          v-for="action in auditActions"
          :key="action.value"
          :label="action.label"
          :value="action.value"
        />
      </el-select>
    </div>

    <div class="table-frame" v-if="filteredAuditLogs.length > 0">
      <el-table
        :data="filteredAuditLogs"
        stripe
        style="width: 100%"
        :default-sort="{ prop: 'timestamp', order: 'descending' }"
        v-loading="auditLoading"
        row-class-name="audit-row"
        @row-click="openAuditDrawer"
      >
        <el-table-column :label="t('audit.time')" prop="timestamp" width="170" sortable>
          <template #default="{ row }">
            <span class="audit-time">{{ formatTime(row.timestamp) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('audit.user')" prop="user" width="100" />
        <el-table-column :label="t('audit.action')" prop="action" width="150">
          <template #default="{ row }">
            <el-tag :type="actionType(row.action)" size="small">{{ actionLabel(row.action) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('audit.host')" prop="host_id" width="120" class-name="mobile-hidden" label-class-name="mobile-hidden">
          <template #default="{ row }">
            <span class="audit-code">{{ row.host_id || "-" }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('audit.result')" prop="result" width="90">
          <template #default="{ row }">
            <el-tag :type="auditResultType(row.result)" size="small">
              {{ auditResultLabel(row.result) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="t('audit.detail')" prop="detail" min-width="240">
          <template #default="{ row }">
            <span class="detail-text">{{ row.detail || "-" }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <el-empty v-else :description="t('audit.noRecords')" />
  </section>

  <el-drawer v-model="auditDrawerVisible" :title="t('settings.audit.detailTitle')" size="420px">
    <dl v-if="selectedAuditLog" class="audit-detail-list">
      <div>
        <dt>{{ t("audit.time") }}</dt>
        <dd>{{ formatTime(selectedAuditLog.timestamp) }}</dd>
      </div>
      <div>
        <dt>{{ t("audit.user") }}</dt>
        <dd>{{ selectedAuditLog.user || "-" }}</dd>
      </div>
      <div>
        <dt>{{ t("audit.action") }}</dt>
        <dd>{{ actionLabel(selectedAuditLog.action) }}</dd>
      </div>
      <div>
        <dt>{{ t("audit.host") }}</dt>
        <dd>{{ selectedAuditLog.host_id || "-" }}</dd>
      </div>
      <div>
        <dt>{{ t("audit.stack") }}</dt>
        <dd>{{ selectedAuditLog.stack_name || "-" }}</dd>
      </div>
      <div>
        <dt>{{ t("audit.result") }}</dt>
        <dd>{{ auditResultLabel(selectedAuditLog.result) }}</dd>
      </div>
      <div>
        <dt>{{ t("audit.ip") }}</dt>
        <dd>{{ selectedAuditLog.ip_address || "-" }}</dd>
      </div>
      <div class="wide">
        <dt>{{ t("audit.detail") }}</dt>
        <dd>{{ selectedAuditLog.detail || "-" }}</dd>
      </div>
    </dl>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useI18n } from "vue-i18n";
import { RefreshCw, Search } from "@lucide/vue";
import { fetchAuditLogs, type AuditEntry } from "@/api/audit";

defineProps<{ active: boolean }>();
const { t } = useI18n();

const auditLogs = ref<AuditEntry[]>([]);
const auditLoading = ref(false);
const auditSearch = ref("");
const auditResultFilter = ref("");
const auditActionFilter = ref("");
const selectedAuditLog = ref<AuditEntry | null>(null);
const auditDrawerVisible = ref(false);
const auditLimit = 50;

const auditActionKeys: Record<string, string> = {
  "stack.auto_update": "audit.action.autoUpdate",
  "stack.auto_update.configure": "audit.action.autoUpdateConfigure",
  "stack.auto_update.notify": "audit.action.autoUpdateNotify",
  "notifyhub.configure": "audit.action.notifyHubConfigure",
  "stack.start": "audit.action.stack.start",
  "stack.stop": "audit.action.stack.stop",
  "stack.down": "audit.action.stack.down",
  "stack.restart": "audit.action.stack.restart",
  "stack.update": "audit.action.stack.update",
  "stack.delete": "audit.action.stack.delete",
  "stack.service.start": "audit.action.stack.serviceStart",
  "stack.service.stop": "audit.action.stack.serviceStop",
  "stack.service.restart": "audit.action.stack.serviceRestart",
  "stack.compose.save": "audit.action.stack.composeSave",
  "stack.compose.deploy": "audit.action.stack.composeDeploy",
  "update_checks.run": "audit.action.updateChecksRun",
  "settings.update": "audit.action.settings.update",
  "host.create": "audit.action.host.create",
  "host.update": "audit.action.host.update",
  "host.delete": "audit.action.host.delete",
  "host.subscription.configure": "audit.action.host.subscription.configure",
  "host.subscription.renewal": "audit.action.host.subscription.renewal",
  "host.billing_alerts.configure": "audit.action.host.billing_alerts.configure",
  "host.stack_icons.update": "audit.action.host.stack_icons.update",
  "host.test_connection": "audit.action.host.test_connection",
};

type TagType = "success" | "primary" | "warning" | "info" | "danger";

const actionTypes: Record<string, TagType> = {
  "stack.start": "success",
  "stack.stop": "warning",
  "stack.down": "warning",
  "stack.restart": "info",
  "stack.update": "primary",
  "stack.delete": "danger",
  "stack.service.start": "success",
  "stack.service.stop": "warning",
  "stack.service.restart": "info",
  "stack.compose.save": "info",
  "stack.compose.deploy": "primary",
  "update_checks.run": "info",
  "settings.update": "warning",
  "host.create": "success",
  "host.update": "primary",
  "host.delete": "danger",
  "host.stack_icons.update": "info",
  "host.test_connection": "success",
};

const auditActions = computed(() =>
  Array.from(new Set(auditLogs.value.map((row) => row.action)))
    .filter(Boolean)
    .sort()
    .map((action) => ({ value: action, label: actionLabel(action) })),
);

const filteredAuditLogs = computed(() => {
  const q = auditSearch.value.trim().toLowerCase();
  return auditLogs.value.filter((row) => {
    const result = ["failed", "failure"].includes(row.result) ? "error" : row.result;
    if (auditResultFilter.value && result !== auditResultFilter.value) return false;
    if (auditActionFilter.value && row.action !== auditActionFilter.value) return false;
    if (!q) return true;
    return [
      row.user,
      row.action,
      row.host_id,
      row.stack_name,
      row.detail,
      row.ip_address,
    ].some((value) => String(value || "").toLowerCase().includes(q));
  });
});

function auditResultType(result: string): TagType {
  return result === "success" ? "success" : result === "skipped" ? "info" : result === "uncertain" || result === "partial" ? "warning" : "danger";
}

function auditResultLabel(result: string): string {
  return t(result === "success" ? "audit.success" : result === "skipped" ? "audit.skipped" : result === "partial" ? "audit.partial" : result === "uncertain" ? "audit.uncertain" : "audit.failure");
}

function actionLabel(action: string): string {
  const key = auditActionKeys[action];
  return key ? t(key as any) : action;
}

function actionType(action: string): TagType {
  return actionTypes[action] || "info";
}

function formatTime(ts: string): string {
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts || "-";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

async function fetchLogs() {
  if (auditLoading.value) return;
  auditLoading.value = true;
  try {
    auditLogs.value = await fetchAuditLogs({ limit: auditLimit, offset: 0 });
  } catch (e) {
    console.error("Failed to fetch audit logs:", e);
  } finally {
    auditLoading.value = false;
  }
}

function openAuditDrawer(row: AuditEntry) {
  selectedAuditLog.value = row;
  auditDrawerVisible.value = true;
}

onMounted(fetchLogs);
</script>

<style scoped src="./settings-section.css"></style>

<style scoped>
.audit-time {
  font-variant-numeric: tabular-nums;
}

:deep(.audit-row) {
  cursor: pointer;
}

.audit-detail-list {
  display: grid;
  grid-template-columns: 1fr;
  gap: 12px;
  margin: 0;
}

.audit-detail-list div {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-raised);
  padding: 10px 12px;
}

.audit-detail-list dt {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 800;
  margin-bottom: 4px;
}

.audit-detail-list dd {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
}
</style>
