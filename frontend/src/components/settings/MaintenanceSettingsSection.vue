<template>
  <section v-if="active" class="settings-section">
    <div class="section-heading">
      <div>
        <h3>{{ t("settings.sections.maintenance") }}</h3>
        <p>{{ t("settings.maintenance.description") }}</p>
      </div>
      <div class="section-actions">
        <el-button class="ui-button ui-button--muted" @click="$emit('edit-interval')">
          {{ t("settings.maintenance.editInterval") }}
        </el-button>
        <el-button
          type="primary"
          class="ui-button ui-button--primary"
          :loading="checkingUpdates"
          @click="runMaintenanceCheck"
        >
          <el-icon><RefreshCw /></el-icon>
          {{ t("updates.checkNow") }}
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="dashboardStore.updateCheckRunning"
      :title="t('updates.runningTitle')"
      :description="t('updates.runningDesc')"
      type="info"
      show-icon
      :closable="false"
      class="section-alert"
    />

    <div class="table-toolbar">
      <el-input
        v-model="updateSearch"
        class="toolbar-input"
        :placeholder="t('settings.maintenance.searchPlaceholder')"
        clearable
        :prefix-icon="Search"
      />
      <el-select v-model="updateStatusFilter" class="toolbar-select" :placeholder="t('updates.status')">
        <el-option :label="t('apps.chip.all')" value="" />
        <el-option :label="t('update.status.updatable')" value="updatable" />
        <el-option :label="t('update.status.needsAuth')" value="needs_auth" />
        <el-option :label="t('update.status.rateLimited')" value="rate_limited" />
        <el-option :label="t('update.status.checkFailed')" value="check_failed" />
        <el-option :label="t('update.status.upToDate')" value="up_to_date" />
      </el-select>
      <el-button class="ui-button ui-button--muted" @click="openUpdatableApps">
        {{ t("settings.maintenance.openApps") }}
      </el-button>
    </div>

    <div class="table-frame" v-if="filteredUpdateResults.length > 0">
      <el-table :data="filteredUpdateResults" stripe style="width: 100%" v-loading="checkingUpdates">
        <el-table-column :label="t('updates.host')" prop="host_id" width="120">
          <template #default="{ row }">
            <span class="host-code-text">{{ row.host_id }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('updates.image')" prop="image" min-width="300">
          <template #default="{ row }">
            <code class="image-ref">{{ row.image }}</code>
          </template>
        </el-table-column>
        <el-table-column :label="t('updates.status')" width="130">
          <template #default="{ row }">
            <UpdateBadge :status="displayStatus(row as UpdateResult)" />
          </template>
        </el-table-column>
        <el-table-column :label="t('updates.currentDigest')" prop="current_digest" min-width="190" class-name="mobile-hidden" label-class-name="mobile-hidden">
          <template #default="{ row }">
            <span class="digest-text">{{ shortenDigest(row.current_digest) }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('updates.registryDigest')" prop="registry_digest" min-width="190" class-name="mobile-hidden" label-class-name="mobile-hidden">
          <template #default="{ row }">
            <span class="digest-text">{{ shortenDigest(row.registry_digest) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <el-empty v-else :description="t('updates.noResults')" />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { RefreshCw, Search } from "@lucide/vue";
import { useDashboardStore, type UpdateResult } from "@/stores/dashboard";
import UpdateBadge from "@/components/UpdateBadge.vue";

defineProps<{ active: boolean }>();
defineEmits<{ 'edit-interval': [] }>();
const { t } = useI18n();
const router = useRouter();
const dashboardStore = useDashboardStore();

const checkingUpdates = ref(false);
const updateSearch = ref("");
const updateStatusFilter = ref("");

const visibleUpdateResults = computed(() =>
  (dashboardStore.updateResults || []).filter((item) =>
    item.status === "updatable"
    || item.status === "up_to_date"
    || item.status === "needs_auth"
    || item.status === "rate_limited"
    || item.status === "check_failed"
    || item.last_failure_status === "needs_auth"
    || item.last_failure_status === "rate_limited"
    || item.last_failure_status === "check_failed",
  ),
);

const filteredUpdateResults = computed(() => {
  const q = updateSearch.value.trim().toLowerCase();
  return visibleUpdateResults.value.filter((item) => {
    const status = displayStatus(item);
    if (updateStatusFilter.value && status !== updateStatusFilter.value) return false;
    if (!q) return true;
    return item.host_id.toLowerCase().includes(q) || item.image.toLowerCase().includes(q);
  });
});

function displayStatus(item: UpdateResult) {
  return item.last_failure_status || item.status;
}

function shortenDigest(value?: string) {
  return value ? `${value.slice(0, 19)}...` : "-";
}

async function fetchUpdateResults() {
  checkingUpdates.value = true;
  try {
    await dashboardStore.fetchUpdateChecks(true);
  } catch (e) {
    console.error("Failed to fetch update checks:", e);
  } finally {
    checkingUpdates.value = false;
  }
}

async function runMaintenanceCheck() {
  checkingUpdates.value = true;
  try {
    await dashboardStore.runUpdateCheck(true);
  } catch (e) {
    console.error("Failed to run update check:", e);
  } finally {
    checkingUpdates.value = false;
  }
}

function openUpdatableApps() {
  void router.push({ name: "apps", query: { status: "updatable" } });
}

onMounted(fetchUpdateResults);
</script>

<style scoped src="./settings-section.css"></style>

<style scoped>
.image-ref {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  background: var(--code-bg);
  border: 1px solid var(--border-subtle);
  color: var(--text-primary);
  border-radius: var(--radius-xs, 4px);
  padding: 2px 6px;
}

.section-alert {
  border-radius: 8px;
}
</style>
