<template>
  <el-tooltip :content="tooltip" placement="top">
    <div class="auto-update-setting">
      <span class="auto-update-caption">{{ t('autoUpdate.label') }}</span>
      <el-switch
        class="auto-update-switch"
        size="small"
        :model-value="state?.enabled ?? false"
        :loading="saving || !state"
        :disabled="!state || (!!state.unavailable_reason && !state.enabled)"
        :aria-label="t('autoUpdate.label')"
        @change="setEnabled(Boolean($event))"
      />
    </div>
  </el-tooltip>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { ElMessage } from 'element-plus';
import { apiClient } from '@/api/client';

interface AutoUpdateState {
  enabled: boolean;
  reason: string;
  unavailable_reason: string;
}

const props = defineProps<{ hostId: string; stackName: string }>();
const emit = defineEmits<{ refresh: [] }>();
const { t } = useI18n();
const state = ref<AutoUpdateState | null>(null);
const error = ref('');
const saving = ref(false);
let timer: ReturnType<typeof setInterval> | undefined;
let revision = 0;
let disposed = false;
let fetching = false;
const path = computed(() => `/api/hosts/${encodeURIComponent(props.hostId)}/stacks/${encodeURIComponent(props.stackName)}/auto-update`);
const tooltip = computed(() => error.value || state.value?.reason || state.value?.unavailable_reason || t('autoUpdate.label'));

async function load() {
  if (saving.value || fetching) return;
  fetching = true;
  const current = revision;
  try {
    const { data } = await apiClient.get<AutoUpdateState>(path.value);
    if (disposed || current !== revision) return;
    if (state.value && state.value.enabled !== data.enabled) emit('refresh');
    state.value = data;
    error.value = '';
  } catch (err: any) {
    if (!disposed && current === revision) error.value = err.response?.data?.detail || t('autoUpdate.loadError');
  } finally {
    fetching = false;
  }
}

async function setEnabled(enabled: boolean) {
  saving.value = true;
  revision++;
  try {
    const { data } = await apiClient.put(path.value, { enabled });
    if (state.value) Object.assign(state.value, data);
    error.value = '';
    emit('refresh');
  } catch (err: any) {
    error.value = err.response?.data?.detail || t('autoUpdate.saveError');
    ElMessage.error(error.value);
  } finally {
    saving.value = false;
    void load();
  }
}

onMounted(() => {
  void load();
  timer = setInterval(() => { void load(); }, 15000);
});
onUnmounted(() => {
  disposed = true;
  revision++;
  if (timer) clearInterval(timer);
});
</script>

<style scoped>
.auto-update-setting {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  min-height: 32px;
  padding: 0 6px;
}
.auto-update-caption {
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 600;
  white-space: nowrap;
}
.auto-update-switch {
  flex-shrink: 0;
  --el-switch-on-color: var(--accent-cyan);
  --el-switch-off-color: var(--border-strong);
}
.auto-update-switch :deep(.el-switch__action) { background: var(--surface-panel); }
</style>
