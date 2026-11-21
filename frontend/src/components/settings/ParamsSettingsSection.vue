<template>
  <section v-if="active" class="settings-section" v-loading="store.loadingSettings">
    <div class="section-heading">
      <div>
        <h3>{{ t("settings.sections.params") }}</h3>
        <p>{{ t("settings.params.alert") }}</p>
      </div>
      <el-button
        type="primary"
        class="ui-button ui-button--primary"
        :loading="store.savingSettings"
        @click="handleSaveParams"
      >
        {{ t("settings.params.save") }}
      </el-button>
    </div>

    <el-form
      ref="paramsFormRef"
      :model="paramsForm"
      label-position="top"
      class="settings-form params-settings-form"
      :rules="paramsRules"
    >
      <div class="form-cluster">
        <div class="cluster-title">{{ t("settings.params.group.runtime") }}</div>
        <div class="settings-field-list">
          <el-form-item prop="DOCKER_POLL_INTERVAL" class="settings-field-row">
            <template #label>
              <span class="settings-field-label">{{ t("settings.params.dockerPoll") }}</span>
              <span class="settings-field-help">{{ t("settings.params.help.dockerPoll") }}</span>
            </template>
            <div class="input-with-unit">
              <el-input-number v-model="paramsForm.DOCKER_POLL_INTERVAL" :min="5" :max="300" :step="5" />
              <span class="unit-text">{{ t("settings.params.unit.seconds") }}</span>
            </div>
          </el-form-item>

          <el-form-item prop="METRICS_STREAM_INTERVAL" class="settings-field-row">
            <template #label>
              <span class="settings-field-label">{{ t("settings.params.metricsStream") }}</span>
              <span class="settings-field-help">{{ t("settings.params.help.metricsStream") }}</span>
            </template>
            <div class="input-with-unit">
              <el-input-number v-model="paramsForm.METRICS_STREAM_INTERVAL" :min="0.5" :max="10" :step="0.5" />
              <span class="unit-text">{{ t("settings.params.unit.seconds") }}</span>
            </div>
          </el-form-item>

          <el-form-item prop="BACKGROUND_STRUCTURE_REFRESH_INTERVAL" class="settings-field-row">
            <template #label>
              <span class="settings-field-label">{{ t("settings.params.structureRefresh") }}</span>
              <span class="settings-field-help">{{ t("settings.params.help.structureRefresh") }}</span>
            </template>
            <div class="input-with-unit">
              <el-input-number v-model="paramsForm.BACKGROUND_STRUCTURE_REFRESH_INTERVAL" :min="60" :max="86400" :step="60" />
              <span class="unit-text">{{ t("settings.params.unit.seconds") }}</span>
            </div>
          </el-form-item>

          <el-form-item prop="UPDATE_CHECK_INTERVAL" class="settings-field-row">
            <template #label>
              <span class="settings-field-label">{{ t("settings.params.updateCheck") }}</span>
              <span class="settings-field-help">{{ t("settings.params.help.updateCheck") }}</span>
            </template>
            <div class="input-with-unit">
              <el-input-number v-model="paramsForm.UPDATE_CHECK_INTERVAL" :min="3600" :max="172800" :step="3600" />
              <span class="unit-text">{{ t("settings.params.unit.seconds") }}</span>
            </div>
          </el-form-item>
        </div>
      </div>

      <div class="form-cluster">
        <div class="cluster-title">{{ t("settings.params.group.account") }}</div>
        <div class="settings-field-list">
          <el-form-item prop="ADMIN_USERNAME" class="settings-field-row">
            <template #label>
              <span class="settings-field-label">{{ t("settings.params.adminUsername") }}</span>
              <span class="settings-field-help">{{ t("settings.params.help.adminUsername") }}</span>
            </template>
            <el-input v-model="paramsForm.ADMIN_USERNAME" placeholder="admin" minlength="3" />
          </el-form-item>

          <el-form-item prop="JWT_EXPIRE_HOURS" class="settings-field-row">
            <template #label>
              <span class="settings-field-label">{{ t("settings.params.jwtExpire") }}</span>
              <span class="settings-field-help">{{ t("settings.params.help.jwtExpire") }}</span>
            </template>
            <div class="input-with-unit">
              <el-input-number v-model="paramsForm.JWT_EXPIRE_HOURS" :min="1" :max="720" :step="1" />
              <span class="unit-text">{{ t("settings.params.unit.hours") }}</span>
            </div>
          </el-form-item>
        </div>
      </div>

      <div class="form-cluster form-cluster--enrollment">
        <div class="cluster-title">{{ t("settings.params.group.enrollment") }}</div>
        <div class="settings-field-list">
          <el-form-item prop="ENROLLMENT_AGENT_IMAGE" class="settings-field-row">
            <template #label>
              <span class="settings-field-label">{{ t("settings.params.agentImage") }}</span>
              <span class="settings-field-help">{{ t("settings.params.help.agentImage") }}</span>
            </template>
            <el-input v-model="paramsForm.ENROLLMENT_AGENT_IMAGE" class="mono-input" spellcheck="false" />
          </el-form-item>

          <el-form-item prop="ENROLLMENT_PROXY_IMAGE" class="settings-field-row">
            <template #label>
              <span class="settings-field-label">{{ t("settings.params.proxyImage") }}</span>
              <span class="settings-field-help">{{ t("settings.params.help.proxyImage") }}</span>
            </template>
            <el-input v-model="paramsForm.ENROLLMENT_PROXY_IMAGE" class="mono-input" spellcheck="false" />
          </el-form-item>
        </div>
      </div>
    </el-form>

    <details class="settings-inline-details">
      <summary>
        <span>{{ t("settings.sections.security") }}</span>
        <small>{{ t("settings.security.alert") }}</small>
      </summary>
      <el-form label-position="top" class="settings-form inline-security-form">
        <div class="form-grid">
          <el-form-item :label="t('settings.security.jwtSecret')">
            <el-input class="mono-input" v-model="readonlyForm.JWT_SECRET" disabled />
            <div class="form-help">{{ t("settings.security.help.jwtSecret") }}</div>
          </el-form-item>

          <el-form-item :label="t('settings.security.credentialsKey')">
            <el-input class="mono-input" v-model="readonlyForm.CREDENTIALS_KEY" disabled />
            <div class="form-help">{{ t("settings.security.help.credentialsKey") }}</div>
          </el-form-item>

          <el-form-item :label="t('settings.security.adminPassword')">
            <el-input class="mono-input" v-model="readonlyForm.ADMIN_PASSWORD" disabled />
            <div class="form-help">{{ t("settings.security.help.adminPassword") }}</div>
          </el-form-item>
        </div>
      </el-form>
    </details>
    <div class="params-settings-form theme-pour-cluster">
      <div class="form-cluster">
        <div class="cluster-title">{{ t("themePour.title") }}</div>
        <div class="settings-field-list">
          <div class="settings-field-row theme-pour-setting-row">
            <div>
              <div class="settings-field-label">{{ t("themePour.label") }}</div>
              <div class="settings-field-help">{{ t("themePour.help") }}</div>
            </div>
            <div class="theme-pour-preset-bar" role="group" :aria-label="t('themePour.title')">
              <button
                v-for="p in pourPresetOptions"
                :key="p"
                type="button"
                class="theme-pour-preset-btn"
                :class="{ active: theme.activePreset.value === p }"
                @click="theme.applyPreset(p)"
              >
                {{ t(`themePour.preset.${p}`) }}
              </button>
              <span v-if="theme.activePreset.value === 'custom'" class="theme-pour-custom-pill">
                {{ t("themePour.preset.custom") }} · {{ theme.pourConfig.duration }}ms
              </span>
              <button
                type="button"
                class="theme-pour-preset-btn preview"
                @click="theme.toggle($event)"
              >
                {{ t("themePour.preview") }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
    <NotifyHubSettings />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import { apiErrorMessage } from "@/api/errors";
import { useSettingsStore } from "@/stores/settings";
import NotifyHubSettings from "@/components/NotifyHubSettings.vue";
import { useTheme } from "@/composables/useTheme";

defineProps<{ active: boolean }>();
const { t } = useI18n();
const store = useSettingsStore();
const theme = useTheme();
const pourPresetOptions = ["off", "crisp", "standard", "lush"] as const;

const paramsForm = reactive({
  DOCKER_POLL_INTERVAL: 10,
  METRICS_STREAM_INTERVAL: 2,
  BACKGROUND_STRUCTURE_REFRESH_INTERVAL: 3600,
  UPDATE_CHECK_INTERVAL: 43200,
  ADMIN_USERNAME: "admin",
  JWT_EXPIRE_HOURS: 24,
  ENROLLMENT_AGENT_IMAGE: "ghcr.io/virgooooox/fleetge-agent:latest",
  ENROLLMENT_PROXY_IMAGE: "caddy:2-alpine",
});

const paramsFormRef = ref<FormInstance>();
const paramsRules = computed<FormRules>(() => ({
  DOCKER_POLL_INTERVAL: [{ required: true, message: t("settings.params.required"), trigger: "blur" }],
  METRICS_STREAM_INTERVAL: [{ required: true, message: t("settings.params.required"), trigger: "blur" }],
  BACKGROUND_STRUCTURE_REFRESH_INTERVAL: [{ required: true, message: t("settings.params.required"), trigger: "blur" }],
  UPDATE_CHECK_INTERVAL: [{ required: true, message: t("settings.params.required"), trigger: "blur" }],
  ADMIN_USERNAME: [
    { required: true, message: t("settings.params.required"), trigger: "blur" },
    { min: 3, message: t("settings.params.minAdminUsername"), trigger: "blur" },
  ],
  JWT_EXPIRE_HOURS: [{ required: true, message: t("settings.params.required"), trigger: "blur" }],
  ENROLLMENT_AGENT_IMAGE: [{ required: true, message: t("settings.params.required"), trigger: "blur" }],
  ENROLLMENT_PROXY_IMAGE: [{ required: true, message: t("settings.params.required"), trigger: "blur" }],
}));

const readonlyForm = reactive({
  JWT_SECRET: "",
  CREDENTIALS_KEY: "",
  ADMIN_PASSWORD: "",
});

async function loadSettings() {
  try {
    await store.fetchSettings();
    store.settings.forEach((item) => {
      if (item.is_writable && item.key in paramsForm) {
        Object.assign(paramsForm, { [item.key]: item.type === "number" ? Number(item.value) : item.value });
      } else if (!item.is_writable && item.key in readonlyForm) {
        readonlyForm[item.key as keyof typeof readonlyForm] = item.value;
      }
    });
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, t("settings.params.saveError")));
  }
}

async function handleSaveParams() {
  if (!paramsFormRef.value) return;
  await paramsFormRef.value.validate(async (valid) => {
    if (!valid) return;
    try {
      const updates = Object.fromEntries(Object.entries(paramsForm).map(([key, value]) => [key, String(value)]));
      await store.saveSettings(updates);
      ElMessage.success(t("settings.params.saveSuccess"));
    } catch (error) {
      ElMessage.error(apiErrorMessage(error, t("settings.params.saveError")));
    }
  });
}

onMounted(loadSettings);
</script>

<style scoped src="./settings-section.css"></style>

<style scoped>
.settings-form {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.params-settings-form {
  gap: 12px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 18px 24px;
}

.input-with-unit,
.icons-preview-strip {
  display: flex;
  align-items: center;
  gap: 8px;
}

.unit-text,
.form-help {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.form-help {
  margin-top: 6px;
}


.settings-inline-details {
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--surface-panel-raised);
}

.settings-inline-details summary {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  cursor: pointer;
}

.settings-inline-details summary span {
  flex: 0 0 auto;
  color: var(--text-primary);
  font-size: 13px;
  font-weight: 800;
}

.settings-inline-details summary small {
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.4;
}

.inline-security-form {
  border-top: 1px solid var(--border-subtle);
  padding: 16px;
}

.mono-input :deep(.el-input__inner) {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.theme-pour-cluster {
  margin-top: 12px;
}

.theme-pour-setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
}

.theme-pour-preset-bar {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.theme-pour-preset-btn {
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  background: var(--surface-panel-raised);
  color: var(--text-secondary);
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}

.theme-pour-preset-btn:hover {
  color: var(--text-primary);
  border-color: var(--border-strong);
}

.theme-pour-preset-btn.active {
  border-color: var(--nav-active-border);
  background: var(--nav-active-bg);
  color: var(--accent-blue);
}

.theme-pour-preset-btn.preview {
  border-color: color-mix(in srgb, var(--accent-blue) 38%, transparent);
  color: var(--accent-blue);
}

.theme-pour-custom-pill {
  height: 26px;
  padding: 0 9px;
  display: inline-flex;
  align-items: center;
  border: 1px dashed var(--border-strong);
  border-radius: 999px;
  color: var(--text-secondary);
  font-size: 11.5px;
  font-variant-numeric: tabular-nums;
}
</style>
