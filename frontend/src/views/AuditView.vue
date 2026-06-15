<template>
  <div class="audit-layout">
    <header class="page-header">
      <div>
        <div class="section-kicker">Audit Trail</div>
        <h2 class="page-title">操作审计</h2>
      </div>
      <el-button class="page-action-button" @click="$router.push('/')">
        <el-icon><ArrowLeft /></el-icon> 返回
      </el-button>
    </header>

    <div class="table-panel" v-if="logs.length > 0">
      <el-table :data="logs" stripe style="width: 100%" :default-sort="{ prop: 'timestamp', order: 'descending' }">
      <el-table-column label="时间" prop="timestamp" width="170" sortable>
        <template #default="{ row }">
          {{ formatTime(row.timestamp) }}
        </template>
      </el-table-column>
      <el-table-column label="用户" prop="user" width="100" />
      <el-table-column label="操作" prop="action" width="140">
        <template #default="{ row }">
          <el-tag :type="actionType(row.action)" size="small">{{ actionLabel(row.action) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="主机" prop="host_id" width="120" />
      <el-table-column label="Stack" prop="stack_name" width="140">
        <template #default="{ row }">
          {{ row.stack_name || '-' }}
        </template>
      </el-table-column>
      <el-table-column label="结果" prop="result" width="80">
        <template #default="{ row }">
          <el-tag :type="row.result === 'success' ? 'success' : 'danger'" size="small">
            {{ row.result === 'success' ? '成功' : '失败' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="IP" prop="ip_address" width="140" />
      <el-table-column label="详情" prop="detail" min-width="200">
        <template #default="{ row }">
          <span class="detail-text">{{ row.detail || '-' }}</span>
        </template>
      </el-table-column>
      </el-table>
    </div>

    <el-empty v-else description="暂无操作记录" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import { ArrowLeft } from "@element-plus/icons-vue";
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
let limit = 50;

const actionLabels: Record<string, string> = {
  "stack.start": "启动 Stack",
  "stack.stop": "停止 Stack",
  "stack.restart": "重启 Stack",
  "stack.update": "更新 Stack",
  "stack.compose.save": "保存 Compose",
  "stack.compose.deploy": "部署 Compose",
  "update_checks.run": "检查更新",
};

const actionTypes: Record<string, string> = {
  "stack.start": "success",
  "stack.stop": "warning",
  "stack.restart": "",
  "stack.update": "primary",
  "stack.compose.save": "info",
  "stack.compose.deploy": "primary",
  "update_checks.run": "info",
};

function actionLabel(action: string): string {
  return actionLabels[action] || action;
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
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--page-header-bg);
  padding: 16px;
}
.page-title {
  font-size: 22px;
  font-weight: 700;
  margin: 0;
  color: var(--text-primary);
}
.section-kicker {
  color: var(--accent-blue);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 6px;
}
.page-action-button {
  border-color: var(--border-subtle) !important;
  background: var(--page-header-action-bg) !important;
  color: var(--text-secondary) !important;
}
.page-action-button:hover,
.page-action-button:focus-visible {
  border-color: var(--border-strong) !important;
  color: var(--text-primary) !important;
}
.detail-text {
  font-size: 12px;
  color: var(--text-secondary);
  word-break: break-all;
}
.table-panel {
  overflow-x: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel);
}
</style>
