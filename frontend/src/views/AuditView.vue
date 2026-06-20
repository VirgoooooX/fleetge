<template>
  <div class="audit-layout">
    <header class="ui-page-header">
      <div>
        <div class="ui-section-kicker">{{ t('audit.kicker') }}</div>
        <h2 class="ui-page-title">{{ t('audit.title') }}</h2>
      </div>
      <el-button class="ui-button ui-button--muted" @click="$router.push('/')">
        <el-icon><ArrowLeft /></el-icon> {{ t('audit.back') }}
      </el-button>
    </header>

    <div class="ui-panel table-panel" v-if="logs.length > 0">
      <el-table :data="logs" stripe style="width: 100%" :default-sort="{ prop: 'timestamp', order: 'descending' }">
      <el-table-column :label="t('audit.time')" prop="timestamp" width="170" sortable>
        <template #default="{ row }">
          <span class="audit-time">{{ formatTime(row.timestamp) }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('audit.user')" prop="user" width="100" />
      <el-table-column :label="t('audit.action')" prop="action" width="140">
        <template #default="{ row }">
          <el-tag :type="actionType(row.action)" size="small">{{ actionLabel(row.action) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('audit.host')" prop="host_id" width="120">
        <template #default="{ row }">
          <span class="audit-code">{{ row.host_id }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('audit.stack')" prop="stack_name" width="140">
        <template #default="{ row }">
          {{ row.stack_name || '-' }}
        </template>
      </el-table-column>
      <el-table-column :label="t('audit.result')" prop="result" width="80">
        <template #default="{ row }">
          <el-tag :type="row.result === 'success' ? 'success' : 'danger'" size="small">
            {{ row.result === 'success' ? t('audit.success') : t('audit.failure') }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column :label="t('audit.ip')" prop="ip_address" width="140">
        <template #default="{ row }">
          <span class="audit-code">{{ row.ip_address || "-" }}</span>
        </template>
      </el-table-column>
      <el-table-column :label="t('audit.detail')" prop="detail" min-width="200">
        <template #default="{ row }">
          <span class="detail-text">{{ row.detail || '-' }}</span>
        </template>
      </el-table-column>
      </el-table>
    </div>

    <el-empty v-else :description="t('audit.noRecords')" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import { ArrowLeft } from "@element-plus/icons-vue";
import { useI18n } from "vue-i18n";
import { apiClient } from "@/api/client";
import dayjs from "dayjs";

interface AuditEntry {
  id: number;
  timestamp: string;
  user: string;
  action: string;
  host_id: string;
  stack_name?: string;
  result: string;
  detail?: string;
  ip_address?: string;
}

const logs = ref<AuditEntry[]>([]);
const { t } = useI18n();
let limit = 50;

const auditActionKeys: Record<string, string> = {
  "stack.start": "audit.action.stack.start",
  "stack.stop": "audit.action.stack.stop",
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
  "host.stack_icons.update": "audit.action.host.stack_icons.update",
  "host.test_connection": "audit.action.host.test_connection",
};

const actionTypes: Record<string, string> = {
  "stack.start": "success",
  "stack.stop": "warning",
  "stack.restart": "",
  "stack.update": "primary",
  "stack.delete": "danger",
  "stack.service.start": "success",
  "stack.service.stop": "warning",
  "stack.service.restart": "",
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

function actionLabel(action: string): string {
  const key = auditActionKeys[action];
  return key ? t(key as any) : action;
}

function actionType(action: string): string {
  return actionTypes[action] || "info";
}

function formatTime(ts: string): string {
  return dayjs(ts).format("YYYY-MM-DD HH:mm:ss");
}

async function fetchLogs() {
  try {
    const res = await apiClient.get("/api/audit-logs", {
      params: { limit, offset: 0 },
    });
    logs.value = res.data || [];
  } catch (e) {
    console.error("Failed to fetch audit logs:", e);
  }
}

onMounted(fetchLogs);
</script>

<style scoped>
.audit-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.audit-time {
  font-variant-numeric: tabular-nums;
}

.audit-code,
.detail-text {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  word-break: break-all;
}
.table-panel {
  overflow-x: auto;
}
</style>
