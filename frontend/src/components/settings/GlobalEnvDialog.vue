<template>
  <el-dialog
    v-model="globalEnvDialogVisible"
    :title="t('settings.globalEnv.title', { name: host?.display_name })"
    width="min(720px, calc(100vw - 24px))"
    class="ui-dialog"
  >
    <div class="global-env-dialog" v-loading="globalEnvLoading">
      <el-alert
        :title="t('settings.globalEnv.help')"
        type="info"
        show-icon
        :closable="false"
      />
      <el-input
        v-model="globalEnvContent"
        type="textarea"
        :rows="16"
        resize="vertical"
        spellcheck="false"
        placeholder="TZ=Asia/Shanghai"
        class="global-env-textarea"
      />
    </div>
    <template #footer>
      <div class="dialog-actions-row">
        <el-button class="ui-button ui-button--muted" @click="globalEnvDialogVisible = false">{{ t("compose.cancel") }}</el-button>
        <el-button class="ui-button ui-button--primary" type="primary" :disabled="!loaded" @click="saveGlobalEnv" :loading="Boolean(host && store.savingGlobalEnv.has(host.host_id))">
          {{ t("settings.globalEnv.save") }}
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import { apiErrorMessage } from "@/api/errors";
import { useSettingsStore, type HostConfigResponse } from "@/stores/settings";

const { t } = useI18n();
const store = useSettingsStore();
const host = ref<HostConfigResponse>();
const globalEnvDialogVisible = ref(false);
const globalEnvLoading = ref(false);
const globalEnvContent = ref("");
const loaded = ref(false);
let request = 0;

watch(globalEnvDialogVisible, (visible) => {
  if (visible) return;
  ++request;
  globalEnvContent.value = "";
  loaded.value = false;
}, { flush: "sync" });

async function open(row: HostConfigResponse) {
  const id = ++request;
  host.value = row;
  globalEnvContent.value = "";
  loaded.value = false;
  globalEnvDialogVisible.value = true;
  globalEnvLoading.value = true;
  try {
    const content = await store.fetchGlobalEnv(row.host_id);
    if (id === request) {
      globalEnvContent.value = content;
      loaded.value = true;
    }
  } catch (error) {
    if (id === request) ElMessage.error(apiErrorMessage(error, t("settings.globalEnv.fetchError")));
  } finally {
    if (id === request) globalEnvLoading.value = false;
  }
}

async function saveGlobalEnv() {
  const row = host.value;
  if (!row || !loaded.value || store.savingGlobalEnv.has(row.host_id)) return;
  const id = request;
  try {
    await store.saveGlobalEnv(row.host_id, globalEnvContent.value);
    ElMessage.success(t("settings.globalEnv.saveSuccess", { name: row.display_name }));
    if (id === request) globalEnvDialogVisible.value = false;
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t("settings.globalEnv.saveError")));
  }
}

defineExpose({ open });
</script>

<style scoped>
.dialog-actions-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 16px;
}


.global-env-dialog {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.global-env-textarea :deep(textarea) {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.global-env-textarea :deep(textarea) {
  font-size: 12px;
  line-height: 1.55;
}
</style>
