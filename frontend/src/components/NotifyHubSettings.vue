<template>
  <el-form
    class="settings-form params-settings-form notify-hub-settings"
    label-position="top"
    :model="form"
    v-loading="loading"
    @submit.prevent="save"
  >
    <div class="form-cluster">
      <div class="cluster-title">Notify Hub</div>
      <div class="settings-field-list">
        <el-form-item class="settings-field-row">
          <template #label>
            <span class="settings-field-label">{{ t('notifyHub.url') }}</span>
            <span class="settings-field-help">{{ t('notifyHub.urlHelp') }}</span>
          </template>
          <el-input v-model="form.url" placeholder="http://192.168.31.100:8788" />
        </el-form-item>
        <el-form-item class="settings-field-row">
          <template #label>
            <span class="settings-field-label">{{ t('notifyHub.recipient') }}</span>
            <span class="settings-field-help">{{ t('notifyHub.recipientHint') }}</span>
          </template>
          <el-input v-model="form.recipient" :placeholder="t('notifyHub.recipient')" />
        </el-form-item>
        <el-form-item class="settings-field-row">
          <template #label>
            <span class="settings-field-label">API Key</span>
            <span class="settings-field-help">{{ keyConfigured ? t('notifyHub.keySaved') : t('notifyHub.keyHelp') }}</span>
          </template>
          <div class="notify-key-field">
            <el-input v-model="form.api_key" type="password" show-password autocomplete="new-password" :placeholder="keyConfigured ? t('notifyHub.keySaved') : 'nfy_…'" />
            <el-checkbox v-if="keyConfigured" v-model="clearKey">{{ t('notifyHub.clearKey') }}</el-checkbox>
          </div>
        </el-form-item>
      </div>
      <div class="notify-save">
        <el-button type="primary" class="ui-button ui-button--primary" :loading="saving" native-type="submit">{{ t('settings.params.save') }}</el-button>
      </div>
    </div>
    <div class="form-cluster billing-alert-settings">
      <div class="cluster-title">{{ t('billingAlerts.title') }}</div>
      <div class="settings-field-list">
        <div class="settings-field-row billing-alert-row">
          <div>
            <div class="settings-field-label">{{ t('billingAlerts.enabled') }}</div>
            <div class="settings-field-help">{{ t('billingAlerts.help') }}</div>
          </div>
          <el-switch v-model="alertsEnabled" :loading="alertsSaving" :disabled="alertsSaving" @change="saveAlertSettings" />
        </div>
      </div>
    </div>
  </el-form>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { ElMessage } from 'element-plus';
import { apiClient } from '@/api/client';
const { t } = useI18n();
const loading = ref(true);
const saving = ref(false);
const keyConfigured = ref(false);
const clearKey = ref(false);
const alertsEnabled = ref(true);
const alertsSaving = ref(false);
const form = reactive({ url: '', recipient: '', api_key: '' });

function apply(data: { url: string; recipient: string; key_configured: boolean }) {
  form.url = data.url;
  form.recipient = data.recipient;
  form.api_key = '';
  keyConfigured.value = data.key_configured;
  clearKey.value = false;
}

onMounted(async () => {
  try {
    const [notifyResponse, alertsResponse] = await Promise.all([
      apiClient.get('/api/admin/notifyhub'),
      apiClient.get('/api/admin/billing-alerts'),
    ]);
    apply(notifyResponse.data);
    alertsEnabled.value = Boolean(alertsResponse.data.enabled);
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || t('autoUpdate.loadError'));
  } finally {
    loading.value = false;
  }
});

async function saveAlertSettings() {
  alertsSaving.value = true;
  try {
    const { data } = await apiClient.put('/api/admin/billing-alerts', { enabled: alertsEnabled.value });
    alertsEnabled.value = Boolean(data.enabled);
    ElMessage.success(t('billingAlerts.saved'));
  } catch (err: any) {
    alertsEnabled.value = !alertsEnabled.value;
    ElMessage.error(err.response?.data?.detail || t('autoUpdate.saveError'));
  } finally {
    alertsSaving.value = false;
  }
}

async function save() {
  saving.value = true;
  try {
    const { data } = await apiClient.put('/api/admin/notifyhub', {
      url: form.url, recipient: form.recipient,
      api_key: clearKey.value ? '' : (form.api_key || null),
    });
    apply(data);
    ElMessage.success(t('settings.params.saveSuccess'));
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || t('autoUpdate.saveError'));
  } finally {
    saving.value = false;
  }
}
</script>

<style scoped>
.notify-hub-settings { margin-top: 12px; }
.billing-alert-settings { margin-top: 14px; }
.billing-alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.notify-key-field {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  width: min(360px, 100%);
}
.notify-save {
  display: flex;
  justify-content: flex-end;
  padding: 11px 16px;
  border-top: 1px solid var(--border-subtle);
  background: color-mix(in srgb, var(--surface-panel) 68%, transparent);
}
</style>
