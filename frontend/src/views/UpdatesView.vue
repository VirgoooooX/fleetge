<template>
  <div class="updates-layout">
    <header class="ui-page-header">
      <div>
        <div class="ui-section-kicker">{{ t('updates.kicker') }}</div>
        <h2 class="ui-page-title">{{ t('updates.title') }}</h2>
      </div>
      <div class="ui-action-row">
        <el-button class="ui-button ui-button--muted" @click="$router.push('/')">
          <el-icon><ArrowLeft /></el-icon> {{ t('updates.back') }}
        </el-button>
        <el-button class="ui-button ui-button--primary" type="primary" :loading="checking" @click="runCheck">
          <el-icon><RefreshCw /></el-icon> {{ t('updates.checkNow') }}
        </el-button>
      </div>
    </header>

    <el-alert
      v-if="updateCheckRunning"
      :title="t('updates.runningTitle')"
      :description="t('updates.runningDesc')"
      type="info"
      show-icon
      :closable="false"
    />

    <div v-if="checking" class="loading-center">
      <el-icon class="is-loading" :size="32"><Loader2 /></el-icon>
      <p>{{ t('updates.checking') }}</p>
    </div>

    <div v-else>
      <div class="ui-panel table-panel" v-if="results.length > 0">
        <el-table :data="results" stripe style="width: 100%">
        <el-table-column :label="t('updates.host')" prop="host_id" width="120">
          <template #default="{ row }">
            <span class="host-text">{{ row.host_id }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('updates.image')" prop="image" min-width="300">
          <template #default="{ row }">
            <code class="image-ref">{{ row.image }}</code>
          </template>
        </el-table-column>
        <el-table-column :label="t('updates.status')" width="120">
          <template #default="{ row }">
            <UpdateBadge :status="displayStatus(row)" />
          </template>
        </el-table-column>
        <el-table-column :label="t('updates.currentDigest')" prop="current_digest" min-width="200">
          <template #default="{ row }">
            <span class="digest-text">{{ row.current_digest ? row.current_digest.slice(0, 19) + '...' : '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('updates.registryDigest')" prop="registry_digest" min-width="200">
          <template #default="{ row }">
            <span class="digest-text">{{ row.registry_digest ? row.registry_digest.slice(0, 19) + '...' : '-' }}</span>
          </template>
        </el-table-column>
        </el-table>
      </div>

      <el-empty v-else :description="t('updates.noResults')" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from "vue";
import { ArrowLeft, RefreshCw, Loader2 } from "@lucide/vue";
import { useI18n } from "vue-i18n";
import { useDashboardStore } from "@/stores/dashboard";
import UpdateBadge from "@/components/UpdateBadge.vue";

interface UpdateResult {
  host_id: string;
  image: string;
  current_digest?: string;
  registry_digest?: string;
  failure_count?: number;
  last_failure_status?: string;
  last_failure_http_status?: number;
  last_failure_retry_after?: number;
  last_failure_at?: string;
  status: string;
}

const results = ref<UpdateResult[]>([]);
const checking = ref(false);
const dashboardStore = useDashboardStore();
const { t } = useI18n();
const updateCheckRunning = computed(() => dashboardStore.updateCheckRunning);

function visibleResults(items: UpdateResult[]) {
  return (items || []).filter((item) =>
    item.status === "updatable" || item.status === "up_to_date"
      || item.status === "needs_auth" || item.status === "rate_limited"
      || item.status === "check_failed"
      || item.last_failure_status === "needs_auth"
      || item.last_failure_status === "rate_limited"
      || item.last_failure_status === "check_failed"
  );
}

function displayStatus(item: UpdateResult) {
  return item.last_failure_status || item.status;
}

async function fetchResults() {
  checking.value = true;
  try {
    results.value = visibleResults(await dashboardStore.fetchUpdateChecks(true));
  } catch (e) {
    console.error("Failed to fetch update checks:", e);
  } finally {
    checking.value = false;
  }
}

async function runCheck() {
  checking.value = true;
  try {
    const runState = await dashboardStore.runUpdateCheck(true);
    results.value = visibleResults(runState.results);
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
.loading-center {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 64px;
  gap: 16px;
  color: var(--text-secondary);
}
.image-ref {
  font-family: var(--font-mono);
  font-size: var(--text-md);
  background: rgba(5, 9, 20, 0.78);
  padding: 2px 6px;
  border-radius: 4px;
}
.host-text,
.digest-text {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}
.table-panel {
  overflow-x: auto;
}
</style>
