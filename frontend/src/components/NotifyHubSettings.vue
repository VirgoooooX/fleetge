<template>
  <div class="form-cluster" v-loading="loading">
    <div class="cluster-title">Notify Hub</div>
    <p class="notify-help">{{ t('notifyHub.help') }}</p>
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item :label="t('notifyHub.url')">
        <el-input v-model="form.url" placeholder="http://192.168.31.100:8788" />
      </el-form-item>
      <el-form-item :label="t('notifyHub.recipient')">
        <el-input v-model="form.recipient" :placeholder="t('notifyHub.recipientHint')" />
      </el-form-item>
      <el-form-item label="API Key">
        <el-input v-model="form.api_key" type="password" show-password autocomplete="new-password" :placeholder="keyConfigured ? t('notifyHub.keySaved') : 'nfy_…'" />
      </el-form-item>
      <el-checkbox v-if="keyConfigured" v-model="clearKey">{{ t('notifyHub.clearKey') }}</el-checkbox>
      <div class="notify-save">
        <el-button type="primary" class="ui-button ui-button--primary" :loading="saving" native-type="submit">{{ t('settings.params.save') }}</el-button>
      </div>
    </el-form>
  </div>
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
    const { data } = await apiClient.get('/api/admin/notifyhub');
    apply(data);
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || t('autoUpdate.loadError'));
  } finally {
    loading.value = false;
  }
});

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
.form-cluster { border-top: 1px solid var(--border-subtle); padding: 20px 0 0; margin-top: 20px; }
.cluster-title { font-weight: 600; }
.notify-help { font-size: 13px; color: var(--text-secondary); line-height: 1.6; }
.notify-save { margin-top: 12px; }
</style>
