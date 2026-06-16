<template>
  <div class="updates-layout">
    <header class="page-header">
      <div>
        <div class="section-kicker">Image Registry</div>
        <h2 class="page-title">镜像更新检测</h2>
      </div>
      <div class="page-actions">
        <el-button class="page-action-button" @click="$router.push('/')">
          <el-icon><ArrowLeft /></el-icon> 返回
        </el-button>
        <el-button type="primary" :loading="checking" @click="runCheck">
          <el-icon><Refresh /></el-icon> 立即检查
        </el-button>
      </div>
    </header>

    <div v-if="checking" class="loading-center">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>正在检查镜像更新...</p>
    </div>

    <div v-else>
      <div class="table-panel" v-if="results.length > 0">
        <el-table :data="results" stripe style="width: 100%">
        <el-table-column label="主机" prop="host_id" width="120" />
        <el-table-column label="镜像" prop="image" min-width="300">
          <template #default="{ row }">
            <code class="image-ref">{{ row.image }}</code>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <UpdateBadge :status="row.status" />
          </template>
        </el-table-column>
        <el-table-column label="当前 Digest" prop="current_digest" min-width="200">
          <template #default="{ row }">
            <span class="digest-text">{{ row.current_digest ? row.current_digest.slice(0, 19) + '...' : '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="仓库 Digest" prop="registry_digest" min-width="200">
          <template #default="{ row }">
            <span class="digest-text">{{ row.registry_digest ? row.registry_digest.slice(0, 19) + '...' : '-' }}</span>
          </template>
        </el-table-column>
        </el-table>
      </div>

      <el-empty v-else description="暂无更新检测结果" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from "vue";
import { ArrowLeft, Refresh, Loading } from "@element-plus/icons-vue";
import { useDashboardStore } from "@/stores/dashboard";
import UpdateBadge from "@/components/UpdateBadge.vue";

interface UpdateResult {
  host_id: string;
  image: string;
  current_digest?: string;
  registry_digest?: string;
  status: string;
}

const results = ref<UpdateResult[]>([]);
const checking = ref(false);
const dashboardStore = useDashboardStore();

function visibleResults(items: UpdateResult[]) {
  return (items || []).filter((item) =>
    item.status === "updatable" || item.status === "up_to_date"
  );
}

async function fetchResults() {
  checking.value = true;
  try {
    results.value = visibleResults(await dashboardStore.fetchUpdateChecks());
  } catch (e) {
    console.error("Failed to fetch update checks:", e);
  } finally {
    checking.value = false;
  }
}

async function runCheck() {
  checking.value = true;
  try {
    results.value = visibleResults(await dashboardStore.runUpdateCheck());
  } catch (e) {
    console.error("Failed to run update check:", e);
  } finally {
    checking.value = false;
  }
}

onMounted(fetchResults);
</script>

<style scoped>
.updates-layout {
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
.page-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: flex-end;
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
.loading-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 64px;
  gap: 16px;
  color: var(--text-secondary);
}
.image-ref {
  font-size: 13px;
  background: rgba(5, 9, 20, 0.78);
  padding: 2px 6px;
  border-radius: 4px;
}
.digest-text {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-secondary);
}
.table-panel {
  overflow-x: auto;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel);
}

@media (max-width: 720px) {
  .page-header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
