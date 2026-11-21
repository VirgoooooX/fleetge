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
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { ElMessage } from 'element-plus';
import { fetchStackAutoUpdate, saveStackAutoUpdate, stackRequestError, type AutoUpdateState } from '@/api/stacks';

const props = defineProps<{ hostId: string; stackName: string }>();
const emit = defineEmits<{ refresh: [] }>();
const { t } = useI18n();
const state = ref<AutoUpdateState | null>(null);
const error = ref('');
const saving = ref(false);
let timer: ReturnType<typeof setInterval> | undefined;
let revision = 0;
let request: AbortController | null = null;
const tooltip = computed(() => error.value || state.value?.reason || state.value?.unavailable_reason || t('autoUpdate.label'));

function cancelLoad() {
  request?.abort();
  request = null;
}

async function load() {
  if (saving.value || request) return;
  const current = revision;
  const controller = new AbortController();
  request = controller;
  try {
    const { data } = await fetchStackAutoUpdate(props.hostId, props.stackName, controller.signal);
    if (current !== revision || request !== controller) return;
    if (state.value && state.value.enabled !== data.enabled) emit('refresh');
    state.value = data;
    error.value = '';
  } catch (err) {
    if (current === revision && request === controller) {
      error.value = stackRequestError(err).detail || t('autoUpdate.loadError');
    }
  } finally {
    if (request === controller) request = null;
  }
}

async function setEnabled(enabled: boolean) {
  if (saving.value || !state.value) return;
  cancelLoad();
  saving.value = true;
  const current = ++revision;
  try {
    const { data } = await saveStackAutoUpdate(props.hostId, props.stackName, enabled);
    if (current !== revision) return;
    state.value = { ...state.value, ...data };
    error.value = '';
    emit('refresh');
  } catch (err) {
    if (current !== revision) return;
    error.value = stackRequestError(err).detail || t('autoUpdate.saveError');
    ElMessage.error(error.value);
  } finally {
    if (current === revision) {
      saving.value = false;
      void load();
    }
  }
}

watch([() => props.hostId, () => props.stackName], () => {
  revision++;
  cancelLoad();
  state.value = null;
  error.value = '';
  saving.value = false;
  void load();
}, { immediate: true });

onMounted(() => {
  timer = setInterval(() => {
    if (!document.hidden) void load();
  }, 15000);
});
onUnmounted(() => {
  revision++;
  cancelLoad();
  if (timer !== undefined) clearInterval(timer);
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
