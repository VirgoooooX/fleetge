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
    <div class="form-cluster billing-alert-settings">
      <div class="cluster-title">{{ t('hostMonitorAlerts.title') }}</div>
      <div class="settings-field-list">
        <div class="settings-field-row billing-alert-row">
          <div>
            <div class="settings-field-label">{{ t('hostMonitorAlerts.enabled') }}</div>
            <div class="settings-field-help">{{ t('hostMonitorAlerts.help') }}</div>
          </div>
          <el-switch v-model="hostMonitorEnabled" :loading="hostMonitorSaving" :disabled="hostMonitorSaving" @change="saveHostMonitorSettings" />
        </div>
        <div class="settings-field-row billing-alert-row">
          <div>
            <div class="settings-field-label">{{ t('hostMonitorAlerts.cleanReboot') }}</div>
            <div class="settings-field-help">{{ t('hostMonitorAlerts.cleanRebootHelp') }}</div>
          </div>
          <el-switch
            v-model="hostMonitorCleanReboot"
            :loading="hostMonitorSaving"
            :disabled="hostMonitorSaving || !hostMonitorEnabled"
            @change="saveHostMonitorSettings"
          />
        </div>
      </div>
    </div>
  </el-form>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { ElMessage } from 'element-plus';
import { apiErrorMessage } from '@/api/errors';
import { notifyHubApi, type NotifyHubSettings } from '@/api/notifyHub';
const { t } = useI18n();
const loading = ref(true);
const saving = ref(false);
const keyConfigured = ref(false);
const clearKey = ref(false);
const alertsEnabled = ref(true);
const alertsSaving = ref(false);
const hostMonitorEnabled = ref(true);
const hostMonitorCleanReboot = ref(true);
const hostMonitorSaving = ref(false);
const form = reactive({ url: '', recipient: '', api_key: '' });

function apply(data: NotifyHubSettings) {
  form.url = data.url;
  form.recipient = data.recipient;
  form.api_key = '';
  keyConfigured.value = data.key_configured;
  clearKey.value = false;
}

const loadController = new AbortController();
onUnmounted(() => loadController.abort());

onMounted(async () => {
  const { signal } = loadController;
  try {
    const [settings, enabled, hostMonitor] = await Promise.all([
      notifyHubApi.getSettings(signal),
      notifyHubApi.getBillingAlerts(signal),
      notifyHubApi.getHostMonitorAlerts(signal),
    ]);
    apply(settings);
    alertsEnabled.value = enabled;
    hostMonitorEnabled.value = hostMonitor.enabled;
    hostMonitorCleanReboot.value = hostMonitor.notify_clean_reboot;
  } catch (error) {
    if (!signal.aborted) ElMessage.error(apiErrorMessage(error, t('notifyHub.loadError')));
  } finally {
    loading.value = false;
  }
});

async function saveAlertSettings() {
  if (alertsSaving.value || loading.value) return;
  const enabled = alertsEnabled.value;
  alertsSaving.value = true;
  try {
    alertsEnabled.value = await notifyHubApi.saveBillingAlerts(enabled);
    ElMessage.success(t('billingAlerts.saved'));
  } catch (error) {
    alertsEnabled.value = !enabled;
    ElMessage.error(apiErrorMessage(error, t('billingAlerts.saveError')));
  } finally {
    alertsSaving.value = false;
  }
}

async function saveHostMonitorSettings() {
  if (hostMonitorSaving.value || loading.value) return;
  const prevEnabled = hostMonitorEnabled.value;
  const prevCleanReboot = hostMonitorCleanReboot.value;
  hostMonitorSaving.value = true;
  try {
    const saved = await notifyHubApi.saveHostMonitorAlerts({
      enabled: prevEnabled,
      notify_clean_reboot: prevCleanReboot,
    });
    hostMonitorEnabled.value = saved.enabled;
    hostMonitorCleanReboot.value = saved.notify_clean_reboot;
    ElMessage.success(t('hostMonitorAlerts.saved'));
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t('hostMonitorAlerts.saveError')));
    try {
      const current = await notifyHubApi.getHostMonitorAlerts();
      hostMonitorEnabled.value = current.enabled;
      hostMonitorCleanReboot.value = current.notify_clean_reboot;
    } catch {
      // keep current UI values if reload also fails
    }
  } finally {
    hostMonitorSaving.value = false;
  }
}

async function save() {
  if (saving.value || loading.value) return;
  saving.value = true;
  try {
    apply(await notifyHubApi.saveSettings({
      url: form.url,
      recipient: form.recipient,
      api_key: clearKey.value ? '' : (form.api_key || null),
    }));
    ElMessage.success(t('settings.params.saveSuccess'));
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t('notifyHub.saveError')));
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
