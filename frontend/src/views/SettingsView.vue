<template>
  <div class="settings-layout">
    <header class="ui-page-header">
      <div>
        <div class="ui-section-kicker">{{ t('settings.kicker') }}</div>
        <h2 class="ui-page-title">{{ t('settings.title') }}</h2>
      </div>
      <el-button class="ui-button ui-button--muted" @click="$router.push('/')">
        <el-icon><ArrowLeft /></el-icon> {{ t('settings.back') }}
      </el-button>
    </header>

    <div class="ui-panel settings-panel">
      <el-tabs v-model="activeTab" type="card" class="settings-tabs">
        <!-- Tab 1: Running parameters -->
        <el-tab-pane name="params" :label="t('settings.tab.params')">
          <div class="tab-pane-content" v-loading="store.loading">
            <el-alert
              :title="t('settings.params.alert')"
              type="info"
              show-icon
              :closable="false"
              class="tab-alert"
            />
            
            <el-form :model="paramsForm" label-position="top" class="ui-form" ref="paramsFormRef" :rules="paramsRules">
              <div class="form-grid">
                <el-form-item :label="t('settings.params.dockerPoll')" prop="DOCKER_POLL_INTERVAL">
                  <div class="input-with-unit">
                    <el-input-number v-model="paramsForm.DOCKER_POLL_INTERVAL" :min="5" :max="300" :step="5" />
                    <span class="unit-text">{{ t('settings.params.unit.seconds') }}</span>
                  </div>
                  <div class="form-help">{{ t('settings.params.help.dockerPoll') }}</div>
                </el-form-item>

                <el-form-item :label="t('settings.params.metricsStream')" prop="METRICS_STREAM_INTERVAL">
                  <div class="input-with-unit">
                    <el-input-number v-model="paramsForm.METRICS_STREAM_INTERVAL" :min="0.5" :max="10" :step="0.5" />
                    <span class="unit-text">{{ t('settings.params.unit.seconds') }}</span>
                  </div>
                  <div class="form-help">{{ t('settings.params.help.metricsStream') }}</div>
                </el-form-item>

                <el-form-item :label="t('settings.params.structureRefresh')" prop="BACKGROUND_STRUCTURE_REFRESH_INTERVAL">
                  <div class="input-with-unit">
                    <el-input-number v-model="paramsForm.BACKGROUND_STRUCTURE_REFRESH_INTERVAL" :min="60" :max="86400" :step="60" />
                    <span class="unit-text">{{ t('settings.params.unit.seconds') }}</span>
                  </div>
                  <div class="form-help">{{ t('settings.params.help.structureRefresh') }}</div>
                </el-form-item>

                <el-form-item :label="t('settings.params.updateCheck')" prop="UPDATE_CHECK_INTERVAL">
                  <div class="input-with-unit">
                    <el-input-number v-model="paramsForm.UPDATE_CHECK_INTERVAL" :min="3600" :max="172800" :step="3600" />
                    <span class="unit-text">{{ t('settings.params.unit.seconds') }}</span>
                  </div>
                  <div class="form-help">{{ t('settings.params.help.updateCheck') }}</div>
                </el-form-item>

                <el-form-item :label="t('settings.params.adminUsername')" prop="ADMIN_USERNAME">
                  <el-input v-model="paramsForm.ADMIN_USERNAME" placeholder="admin" minlength="3" />
                  <div class="form-help">{{ t('settings.params.help.adminUsername') }}</div>
                </el-form-item>

                <el-form-item :label="t('settings.params.jwtExpire')" prop="JWT_EXPIRE_HOURS">
                  <div class="input-with-unit">
                    <el-input-number v-model="paramsForm.JWT_EXPIRE_HOURS" :min="1" :max="720" :step="1" />
                    <span class="unit-text">{{ t('settings.params.unit.hours') }}</span>
                  </div>
                  <div class="form-help">{{ t('settings.params.help.jwtExpire') }}</div>
                </el-form-item>
              </div>

              <el-form-item class="form-actions-row">
                <el-button type="primary" class="ui-button" :loading="store.saving" @click="handleSaveParams">
                  {{ t('settings.params.save') }}
                </el-button>
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>

        <!-- Tab 2: Security & Credentials -->
        <el-tab-pane name="security" :label="t('settings.tab.security')">
          <div class="tab-pane-content" v-loading="store.loading">
            <el-alert
              :title="t('settings.security.alert')"
              type="warning"
              show-icon
              :closable="false"
              class="tab-alert"
            />

            <el-form label-position="top" class="ui-form">
              <div class="form-grid">
                <el-form-item :label="t('settings.security.jwtSecret')">
                  <el-input class="mono-input" v-model="readonlyForm.JWT_SECRET" disabled show-password />
                  <div class="form-help">{{ t('settings.security.help.jwtSecret') }}</div>
                </el-form-item>

                <el-form-item :label="t('settings.security.credentialsKey')">
                  <el-input class="mono-input" v-model="readonlyForm.CREDENTIALS_KEY" disabled show-password />
                  <div class="form-help">{{ t('settings.security.help.credentialsKey') }}</div>
                </el-form-item>

                <el-form-item :label="t('settings.security.adminPassword')">
                  <el-input class="mono-input" v-model="readonlyForm.ADMIN_PASSWORD" disabled show-password />
                  <div class="form-help">{{ t('settings.security.help.adminPassword') }}</div>
                </el-form-item>
              </div>
            </el-form>
          </div>
        </el-tab-pane>

        <!-- Tab 3: Host Node Management -->
        <el-tab-pane name="hosts" :label="t('settings.tab.hosts')">
          <div class="tab-pane-content" v-loading="store.loading">
            <div class="pane-header-actions">
              <div class="pane-header-kicker">{{ t('settings.hosts.count', { count: store.hosts.length }) }}</div>
              <el-button type="primary" class="ui-button ui-button--compact" :icon="Plus" @click="openCreateHostDialog">
                {{ t('settings.hosts.add') }}
              </el-button>
            </div>

            <el-table :data="store.hosts" stripe style="width: 100%" class="host-table">
              <el-table-column :label="t('settings.hosts.col.sort')" prop="sort_order" width="70" align="center" class-name="mobile-hidden" label-class-name="mobile-hidden" />
              <el-table-column :label="t('settings.hosts.col.id')" prop="host_id" width="140" class-name="mobile-hidden" label-class-name="mobile-hidden">
                <template #default="{ row }">
                  <span class="host-code-text">{{ row.host_id }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="t('settings.hosts.col.name')" prop="display_name" width="160" />
              <el-table-column :label="t('settings.hosts.col.url')" min-width="200" prop="agent_url" class-name="mobile-hidden" label-class-name="mobile-hidden">
                <template #default="{ row }">
                  <span class="host-code-text">{{ row.agent_url || "-" }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="t('settings.hosts.col.status')" prop="enabled" width="90" align="center">
                <template #default="{ row }">
                  <el-switch v-slot:default v-model="row.enabled" @change="toggleHostEnabled(row)" :loading="store.saving" />
                </template>
              </el-table-column>
              <el-table-column :label="t('settings.hosts.col.appProfiles')" width="130" align="center" class-name="mobile-hidden" label-class-name="mobile-hidden">
                <template #default="{ row }">
                  <div class="icons-cell">
                    <div class="icons-preview-strip" v-if="row.app_profiles && row.app_profiles.length > 0">
                      <el-tooltip
                        v-for="(p, idx) in row.app_profiles.slice(0, 3)"
                        :key="idx"
                        :content="p.title || p.stack_pattern"
                        placement="top"
                      >
                        <el-image
                          v-if="p.icon_value"
                          :src="getIconUrl(p.icon_value)"
                          class="icon-strip-thumb"
                          fit="contain"
                        >
                          <template #error>
                            <el-icon class="icon-strip-placeholder"><Picture /></el-icon>
                          </template>
                        </el-image>
                        <div v-else class="icon-strip-thumb">
                          <el-icon class="icon-strip-placeholder"><Picture /></el-icon>
                        </div>
                      </el-tooltip>
                      <span
                        v-if="row.app_profiles.length > 3"
                        class="icons-more-chip"
                      >+{{ row.app_profiles.length - 3 }}</span>
                    </div>
                    <span v-else class="icons-empty">—</span>
                    <el-tooltip :content="t('settings.hosts.col.manageAppProfiles')" placement="top">
                      <el-button
                        size="small"
                        :icon="SettingIcon"
                        circle
                        class="icons-manage-btn"
                        @click="openAppProfilesDialog(row)"
                      />
                    </el-tooltip>
                  </div>
                </template>
              </el-table-column>
              <el-table-column :label="t('settings.hosts.col.actions')" :width="isMobile ? 160 : 280" align="center" :fixed="isMobile ? false : 'right'">
                <template #default="{ row }">
                  <div class="row-operations">
                    <el-button size="small" type="success" plain @click="testHostConnection(row)">
                      <el-icon v-if="isMobile"><Link /></el-icon>
                      <span v-else>{{ t('settings.hosts.action.test') }}</span>
                    </el-button>
                    <el-tooltip :content="t('settings.globalEnv.manage')" placement="top">
                      <el-button size="small" type="info" plain :icon="Document" @click="openGlobalEnvDialog(row)" />
                    </el-tooltip>
                    <el-button size="small" type="info" plain :icon="Edit" @click="openEditHostDialog(row)" />
                    <el-button size="small" type="danger" plain :icon="Delete" @click="confirmDeleteHost(row)" />
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- Host Create / Edit Dialog -->
    <el-dialog
      v-model="hostDialogVisible"
      :title="hostFormMode === 'create' ? t('settings.hosts.create') : t('settings.hosts.edit')"
      width="640px"
      custom-class="ui-dialog"
      :before-close="closeHostDialog"
    >
      <el-form :model="hostForm" label-position="top" ref="hostFormRef" :rules="hostRules" v-loading="hostFormLoading">
        <div class="dialog-grid">
          <el-form-item :label="t('settings.hosts.form.id')" prop="host_id">
            <el-input
              class="mono-input"
              v-model="hostForm.host_id"
              :placeholder="t('settings.hosts.form.idPlaceholder')"
              :disabled="hostFormMode === 'edit'"
            />
          </el-form-item>

          <el-form-item :label="t('settings.hosts.form.name')" prop="display_name">
            <el-input v-model="hostForm.display_name" :placeholder="t('settings.hosts.form.namePlaceholder')" />
          </el-form-item>

          <el-form-item :label="t('settings.hosts.form.sort')" prop="sort_order">
            <el-input-number v-model="hostForm.sort_order" :min="0" />
          </el-form-item>

          <el-form-item :label="t('settings.hosts.form.enabled')" prop="enabled">
            <el-switch v-model="hostForm.enabled" />
          </el-form-item>
        </div>

        <el-divider>{{ t('settings.hosts.form.connection') }}</el-divider>

        <div class="mode-section">
          <el-form-item :label="t('settings.hosts.form.agentUrl')" prop="agent_url">
            <el-input class="mono-input" v-model="hostForm.agent_url" placeholder="http://192.168.1.100:8080" />
            <div class="form-help">{{ t('settings.hosts.form.agentUrlHelp') }}</div>
          </el-form-item>
          <el-form-item :label="t('settings.hosts.form.agentToken')" prop="agent_token">
            <el-input
              class="mono-input"
              v-model="hostForm.agent_token"
              type="password"
              show-password
              :placeholder="hostFormMode === 'edit' ? t('settings.hosts.form.unchangedPlaceholder') : t('settings.hosts.form.agentTokenPlaceholder')"
            />
          </el-form-item>
        </div>

        <div class="dialog-actions-row">
          <el-button type="success" plain @click="testFormConnection" :loading="testConnectionLoading">
            {{ t('settings.hosts.action.test') }}
          </el-button>
          <div class="spacer"></div>
          <el-button @click="closeHostDialog">{{ t('compose.cancel') }}</el-button>
          <el-button type="primary" @click="saveHostForm">{{ t('compose.saveAction') }}</el-button>
        </div>
      </el-form>
    </el-dialog>

    <!-- App Profiles Management Dialog -->
    <el-dialog
      v-model="appProfilesDialogVisible"
      :title="t('settings.appProfiles.title', { name: selectedHost?.display_name })"
      width="880px"
      custom-class="ui-dialog"
    >
      <div class="icons-dialog-body" v-loading="appProfilesLoading">
        <div class="current-icons-section">
          <div class="section-kicker">{{ t('settings.appProfiles.existing') }}</div>
          <el-table :data="appProfilesList" stripe size="small" class="icons-table" max-height="300px">
            <el-table-column :label="t('settings.appProfiles.col.pattern')" prop="stack_pattern" width="130">
              <template #default="{ row }">
                <code class="pattern-code">{{ row.stack_pattern }}</code>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.title')" prop="title" width="130">
              <template #default="{ row }">
                <span>{{ row.title || "-" }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.url')" prop="app_url" min-width="150">
              <template #default="{ row }">
                <span class="url-text font-mono">{{ row.app_url || "-" }}</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.group')" prop="group" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.group" size="small">{{ row.group }}</el-tag>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.icon')" width="80" align="center">
              <template #default="{ row }">
                <el-image v-if="row.icon_value" :src="getIconUrl(row.icon_value)" class="icon-preview-cell" fit="contain">
                  <template #error>
                    <el-icon class="icon-placeholder-cell"><Picture /></el-icon>
                  </template>
                </el-image>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.actions')" width="80" align="center">
              <template #default="{ $index }">
                <el-button size="small" type="danger" :icon="Delete" circle @click="removeAppProfile($index)" />
              </template>
            </el-table-column>
          </el-table>
        </div>

        <el-divider>{{ t('settings.appProfiles.addNew') }}</el-divider>

        <el-form :model="appProfileForm" label-position="top" class="add-icon-form" ref="appProfileFormRef" :rules="appProfileRules">
          <div class="icon-form-grid">
            <el-form-item :label="t('settings.appProfiles.form.pattern')" prop="stack_pattern">
              <el-input v-model="appProfileForm.stack_pattern" :placeholder="t('settings.appProfiles.form.patternPlaceholder')" />
              <div class="form-help" v-html="t('settings.icons.form.patternHelp')"></div>
            </el-form-item>

            <el-form-item :label="t('settings.appProfiles.form.title')" prop="title">
              <el-input v-model="appProfileForm.title" :placeholder="t('settings.appProfiles.form.titlePlaceholder')" />
            </el-form-item>

            <el-form-item :label="t('settings.appProfiles.form.url')" prop="app_url">
              <el-input v-model="appProfileForm.app_url" :placeholder="t('settings.appProfiles.form.urlPlaceholder')" />
            </el-form-item>

            <el-form-item :label="t('settings.appProfiles.form.group')" prop="group">
              <el-input v-model="appProfileForm.group" :placeholder="t('settings.appProfiles.form.groupPlaceholder')" />
            </el-form-item>

            <el-form-item :label="t('settings.appProfiles.form.source')">
              <el-radio-group v-model="appProfileForm.sourceType" size="small">
                <el-radio-button label="none">{{ t('apps.chip.all') }} (None)</el-radio-button>
                <el-radio-button label="url">{{ t('settings.appProfiles.form.remoteUrl') }}</el-radio-button>
                <el-radio-button label="local">{{ t('settings.appProfiles.form.localFile') }}</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <!-- URL Source -->
            <el-form-item v-if="appProfileForm.sourceType === 'url'" :label="t('settings.appProfiles.form.remoteUrl')" prop="icon_url">
              <el-input v-model="appProfileForm.icon_url" placeholder="https://cdn.jsdelivr.net/.../logo.svg" />
            </el-form-item>

            <!-- Local Source -->
            <el-form-item v-else-if="appProfileForm.sourceType === 'local'" :label="t('settings.appProfiles.form.localFile')" prop="icon_file">
              <div class="local-file-picker">
                <el-select v-model="appProfileForm.icon_file" :placeholder="t('settings.appProfiles.form.localPlaceholder')" class="file-select">
                  <el-option v-for="file in availableFiles" :key="file" :label="file" :value="file" />
                </el-select>
                
                <el-upload
                  action="#"
                  :auto-upload="false"
                  :show-file-list="false"
                  :on-change="handleIconFileSelected"
                  class="upload-trigger"
                >
                  <el-button type="info" :icon="Upload" class="ui-button ui-button--muted">{{ t('settings.appProfiles.form.upload') }}</el-button>
                </el-upload>
              </div>
            </el-form-item>
          </div>

          <div class="icon-form-action">
            <el-button type="primary" class="ui-button ui-button--compact" @click="addAppProfile">
              {{ t('settings.appProfiles.form.addBtn') }}
            </el-button>
          </div>
        </el-form>
      </div>

      <template #footer>
        <div class="dialog-actions-row">
          <el-button @click="appProfilesDialogVisible = false">{{ t('compose.cancel') }}</el-button>
          <el-button type="primary" @click="saveAppProfiles" :loading="store.saving">{{ t('settings.appProfiles.form.saveBtn') }}</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- global.env Dialog -->
    <el-dialog
      v-model="globalEnvDialogVisible"
      :title="t('settings.globalEnv.title', { name: selectedHost?.display_name })"
      width="720px"
      custom-class="ui-dialog"
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
          <el-button @click="globalEnvDialogVisible = false">{{ t('compose.cancel') }}</el-button>
          <el-button type="primary" @click="saveGlobalEnv" :loading="store.saving">
            {{ t('settings.globalEnv.save') }}
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage, ElMessageBox } from "element-plus";
import type { FormInstance, FormRules } from "element-plus";
import { useConfirm } from "@/composables/useConfirm";
import {
  ArrowLeft,
  Plus,
  Edit,
  Delete,
  Picture,
  Upload,
  Setting as SettingIcon,
  Link,
  Document,
} from "@element-plus/icons-vue";
import { useSettingsStore, type SettingItem, type HostConfigResponse, type StackIconEntry, type AppProfileEntry } from "@/stores/settings";
import { useMobile } from "@/composables/useMobile";

const { t } = useI18n();
const store = useSettingsStore();
const { confirm, alert: confirmAlert } = useConfirm();
const { isMobile } = useMobile();
const activeTab = ref("params");

// Params Form
const paramsForm = reactive<Record<string, any>>({
  DOCKER_POLL_INTERVAL: 10,
  METRICS_STREAM_INTERVAL: 1,
  BACKGROUND_STRUCTURE_REFRESH_INTERVAL: 3600,
  UPDATE_CHECK_INTERVAL: 43200,
  ADMIN_USERNAME: "admin",
  JWT_EXPIRE_HOURS: 24,
});

const paramsFormRef = ref<FormInstance>();
const paramsRules = reactive<FormRules>({
  DOCKER_POLL_INTERVAL: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
  METRICS_STREAM_INTERVAL: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
  BACKGROUND_STRUCTURE_REFRESH_INTERVAL: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
  UPDATE_CHECK_INTERVAL: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
  ADMIN_USERNAME: [
    { required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" },
    { min: 3, message: t("settings.hosts.form.required.id"), trigger: "blur" }
  ],
  JWT_EXPIRE_HOURS: [{ required: true, message: t("settings.hosts.form.required.id"), trigger: "blur" }],
});

// Readonly Fields
const readonlyForm = reactive({
  JWT_SECRET: "",
  CREDENTIALS_KEY: "",
  ADMIN_PASSWORD: "",
});

// Load all configuration lists
async function loadSettings() {
  try {
    await store.fetchSettings();
    // Hydrate forms
    store.settings.forEach((item) => {
      if (item.is_writable) {
        if (item.type === "number") {
          paramsForm[item.key] = Number(item.value);
        } else {
          paramsForm[item.key] = item.value;
        }
      } else {
        if (item.key in readonlyForm) {
          (readonlyForm as any)[item.key] = item.value;
        }
      }
    });
  } catch (err: any) {
    ElMessage.error(store.error || t("settings.params.saveError"));
  }
}

async function handleSaveParams() {
  if (!paramsFormRef.value) return;
  await paramsFormRef.value.validate(async (valid) => {
    if (!valid) return;
    try {
      const updates: Record<string, string> = {};
      Object.keys(paramsForm).forEach((key) => {
        updates[key] = String(paramsForm[key]);
      });
      await store.saveSettings(updates);
      ElMessage.success(t("settings.params.saveSuccess"));
    } catch (err: any) {
      ElMessage.error(store.error || t("settings.params.saveError"));
    }
  });
}

// Host Management Tab
const hostDialogVisible = ref(false);
const hostFormMode = ref<"create" | "edit">("create");
const hostFormLoading = ref(false);
const testConnectionLoading = ref(false);
const hostFormRef = ref<FormInstance>();

const hostForm = reactive({
  host_id: "",
  display_name: "",
  enabled: true,
  sort_order: 0,
  
  // Agent Mode
  agent_url: "",
  agent_token: "",
});

const validateHostId = (_rule: any, value: string, callback: any) => {
  if (!value) {
    callback(new Error(t("settings.hosts.form.required.id")));
  } else if (!/^[a-z0-9][a-z0-9-]*$/.test(value)) {
    callback(new Error(t("settings.hosts.form.invalid.id")));
  } else {
    callback();
  }
};

const validateHttpUrl = (_rule: any, value: string, callback: any) => {
  if (value && !/^https?:\/\//.test(value)) {
    callback(new Error(t("settings.hosts.form.invalid.url")));
  } else {
    callback();
  }
};

const hostRules = reactive<FormRules>({
  host_id: [{ required: true, validator: validateHostId, trigger: "blur" }],
  display_name: [{ required: true, message: t("settings.hosts.form.required.name"), trigger: "blur" }],
  agent_url: [
    { required: true, message: t("settings.hosts.form.required.agentUrl"), trigger: "blur" },
    { validator: validateHttpUrl, trigger: "blur" }
  ],
});

function openCreateHostDialog() {
  hostFormMode.value = "create";
  hostForm.host_id = "";
  hostForm.display_name = "";
  hostForm.enabled = true;
  hostForm.sort_order = store.hosts.length > 0 ? Math.max(...store.hosts.map(h => h.sort_order)) + 10 : 10;
  hostForm.agent_url = "";
  hostForm.agent_token = "";
  
  hostDialogVisible.value = true;
}

function openEditHostDialog(row: HostConfigResponse) {
  hostFormMode.value = "edit";
  hostForm.host_id = row.host_id;
  hostForm.display_name = row.display_name;
  hostForm.enabled = row.enabled;
  hostForm.sort_order = row.sort_order;
  
  hostForm.agent_url = row.agent_url || "";
  hostForm.agent_token = ""; // Password fields are masked
  
  hostDialogVisible.value = true;
}

function closeHostDialog() {
  hostDialogVisible.value = false;
  if (hostFormRef.value) {
    hostFormRef.value.clearValidate();
  }
}

// Transform form values to request payload shapes
function prepareHostPayload() {
  const payload: any = {
    display_name: hostForm.display_name,
    enabled: hostForm.enabled,
    sort_order: hostForm.sort_order,
    agent_url: hostForm.agent_url,
    agent_token: hostForm.agent_token || (hostFormMode.value === "edit" ? null : ""),
  };

  if (hostFormMode.value === "create") {
    payload.host_id = hostForm.host_id;
  }
  
  return payload;
}

async function saveHostForm() {
  if (!hostFormRef.value) return;
  await hostFormRef.value.validate(async (valid) => {
    if (!valid) return;
    hostFormLoading.value = true;
    try {
      const payload = prepareHostPayload();
      if (hostFormMode.value === "create") {
        await store.createHost(payload);
        ElMessage.success(t("settings.hosts.create.success"));
      } else {
        await store.updateHost(hostForm.host_id, payload);
        ElMessage.success(t("settings.hosts.update.success"));
      }
      closeHostDialog();
    } catch (err: any) {
      ElMessage.error(err || t("settings.hosts.save.error"));
    } finally {
      hostFormLoading.value = false;
    }
  });
}

async function toggleHostEnabled(row: HostConfigResponse) {
  try {
    const payload = {
      display_name: row.display_name,
      enabled: row.enabled,
      sort_order: row.sort_order,
      agent_url: row.agent_url,
      agent_token: null, // Keep secrets unchanged
    };
    await store.updateHost(row.host_id, payload);
    ElMessage.success(
      t(row.enabled ? "settings.hosts.toggle.enabledSuccess" : "settings.hosts.toggle.disabledSuccess", { name: row.display_name })
    );
  } catch (err: any) {
    row.enabled = !row.enabled; // Rollback switch state
    ElMessage.error(err || t("settings.hosts.toggle.error"));
  }
}

async function confirmDeleteHost(row: HostConfigResponse) {
  try {
    await confirm(
      t("settings.hosts.delete.confirm", { name: row.display_name }),
      t("settings.hosts.delete.title"),
      {
        tone: "danger",
        confirmButtonText: t("stack.action.delete"),
        cancelButtonText: t("stack.confirm.cancel"),
        confirmButtonClass: "pg-confirm-btn",
      }
    );
    await store.deleteHost(row.host_id);
    ElMessage.success(t("settings.hosts.delete.success", { name: row.display_name }));
  } catch (err: any) {
    if (err !== "cancel") {
      ElMessage.error(err || t("settings.hosts.delete.error"));
    }
  }
}

async function testHostConnection(row: HostConfigResponse) {
  const loadingMsg = ElMessage({
    message: t("settings.hosts.action.testing", { name: row.display_name }),
    duration: 0,
    type: "info",
  });

  const res = await store.testConnection(row.host_id);
  loadingMsg.close();

  if (res.success) {
    confirmAlert(
      t("settings.hosts.test.successDetail", { time: res.response_time_ms, msg: res.message }),
      t("settings.hosts.test.successTitle"),
      { tone: "success", confirmButtonText: t("stack.confirm.ok") }
    );
  } else {
    confirmAlert(
      t("settings.hosts.test.failedDetail", { msg: res.message }),
      t("settings.hosts.test.failedTitle"),
      { tone: "error", confirmButtonText: t("stack.confirm.ok") }
    );
  }
}

async function testFormConnection() {
  if (!hostFormRef.value) return;
  let hasErrors = false;
  hostFormRef.value.validateField(["agent_url"], (valid) => {
    if (!valid) hasErrors = true;
  });
  if (hasErrors) return;

  testConnectionLoading.value = true;
  try {
    const payload = prepareHostPayload();
    if (hostFormMode.value === "create") {
      payload.host_id = hostForm.host_id;
    }
    const res = await store.testNewConnection(payload);
    if (res.success) {
      ElMessage.success(t("settings.hosts.test.newSuccess", { time: res.response_time_ms, msg: res.message }));
    } else {
      ElMessage.error(t("settings.hosts.action.testFailed") + ` ${res.message}`);
    }
  } catch (e: any) {
    ElMessage.error(t("settings.hosts.test.error", { msg: String(e) }));
  } finally {
    testConnectionLoading.value = false;
  }
}

// App Profiles Section
const appProfilesDialogVisible = ref(false);
const selectedHost = ref<HostConfigResponse | null>(null);
const appProfilesLoading = ref(false);
const appProfilesList = ref<AppProfileEntry[]>([]);
const availableFiles = ref<string[]>([]);
const globalEnvDialogVisible = ref(false);
const globalEnvLoading = ref(false);
const globalEnvContent = ref("");

const appProfileForm = reactive({
  stack_pattern: "",
  title: "",
  app_url: "",
  group: "",
  sourceType: "none", // "none" | "url" | "local"
  icon_url: "",
  icon_file: "",
});

const appProfileFormRef = ref<FormInstance>();
const appProfileRules = reactive<FormRules>({
  stack_pattern: [
    { required: true, message: t("settings.icons.required.pattern"), trigger: "blur" }
  ],
  app_url: [
    { validator: validateHttpUrl, trigger: "blur" }
  ],
  icon_url: [
    { validator: validateHttpUrl, trigger: "blur" }
  ],
});

async function openAppProfilesDialog(row: HostConfigResponse) {
  selectedHost.value = row;
  appProfilesList.value = [];
  availableFiles.value = [];
  appProfileForm.stack_pattern = "";
  appProfileForm.title = "";
  appProfileForm.app_url = "";
  appProfileForm.group = "";
  appProfileForm.sourceType = "none";
  appProfileForm.icon_url = "";
  appProfileForm.icon_file = "";
  appProfilesDialogVisible.value = true;
  
  appProfilesLoading.value = true;
  try {
    const res = await store.fetchAppProfiles(row.host_id);
    appProfilesList.value = res.profiles || [];
    availableFiles.value = res.available_files || [];
  } catch (e: any) {
    ElMessage.error(e || t("settings.appProfiles.fetchError"));
  } finally {
    appProfilesLoading.value = false;
  }
}

function isHttpUrl(value: string | null) {
  if (!value) return false;
  return /^https?:\/\//.test(value);
}

function getIconUrl(value: string | null) {
  if (!value) return "";
  if (/^https?:\/\//.test(value)) return value;
  if (value.startsWith("/api/") || value.startsWith("/")) return value;
  return `/api/static/icons/${value}`;
}

function removeAppProfile(index: number) {
  appProfilesList.value.splice(index, 1);
}

async function handleIconFileSelected(uploadFile: any) {
  if (!selectedHost.value) return;
  const rawFile = uploadFile.raw;
  if (!rawFile) return;

  if (rawFile.size > 2 * 1024 * 1024) {
    ElMessage.error(t("settings.icons.upload.tooLarge"));
    return;
  }

  const loadingMsg = ElMessage({
    message: t("settings.icons.upload.progress"),
    duration: 0,
    type: "info",
  });

  try {
    const filename = await store.uploadIcon(selectedHost.value.host_id, rawFile);
    loadingMsg.close();
    ElMessage.success(t("settings.icons.upload.success", { name: filename }));
    
    if (!availableFiles.value.includes(filename)) {
      availableFiles.value.push(filename);
      availableFiles.value.sort();
    }
    appProfileForm.icon_file = filename;
  } catch (e: any) {
    loadingMsg.close();
    ElMessage.error(e || t("settings.icons.upload.error"));
  }
}

async function addAppProfile() {
  if (!appProfileFormRef.value) return;
  
  if (!appProfileForm.stack_pattern.trim()) {
    ElMessage.error(t("settings.icons.required.pattern"));
    return;
  }
  
  let val: string | null = null;
  if (appProfileForm.sourceType === "url") {
    if (!appProfileForm.icon_url.trim()) {
      ElMessage.error(t("settings.icons.required.url"));
      return;
    }
    if (!/^https?:\/\//.test(appProfileForm.icon_url.trim())) {
      ElMessage.error(t("settings.hosts.form.invalid.url"));
      return;
    }
    val = appProfileForm.icon_url.trim();
  } else if (appProfileForm.sourceType === "local") {
    if (!appProfileForm.icon_file) {
      ElMessage.error(t("settings.icons.required.file"));
      return;
    }
    val = appProfileForm.icon_file;
  }

  const dupIndex = appProfilesList.value.findIndex(i => i.stack_pattern === appProfileForm.stack_pattern.trim());
  
  const newProfile: AppProfileEntry = {
    stack_pattern: appProfileForm.stack_pattern.trim(),
    title: appProfileForm.title.trim() || null,
    app_url: appProfileForm.app_url.trim() || null,
    group: appProfileForm.group.trim() || null,
    icon_value: val,
  };

  if (dupIndex > -1) {
    appProfilesList.value[dupIndex] = newProfile;
    ElMessage.info(t("settings.icons.mapping.updated", { pattern: appProfileForm.stack_pattern.trim() }));
  } else {
    appProfilesList.value.push(newProfile);
  }

  appProfileForm.stack_pattern = "";
  appProfileForm.title = "";
  appProfileForm.app_url = "";
  appProfileForm.group = "";
  appProfileForm.sourceType = "none";
  appProfileForm.icon_url = "";
  appProfileForm.icon_file = "";
}

async function saveAppProfiles() {
  if (!selectedHost.value) return;
  try {
    await store.saveAppProfiles(selectedHost.value.host_id, appProfilesList.value);
    ElMessage.success(t("settings.appProfiles.saveSuccess", { name: selectedHost.value.display_name }));
    appProfilesDialogVisible.value = false;
    await store.fetchHosts();
  } catch (e: any) {
    ElMessage.error(e || t("settings.appProfiles.saveError"));
  }
}

async function openGlobalEnvDialog(row: HostConfigResponse) {
  selectedHost.value = row;
  globalEnvContent.value = "";
  globalEnvDialogVisible.value = true;
  globalEnvLoading.value = true;
  try {
    globalEnvContent.value = await store.fetchGlobalEnv(row.host_id);
  } catch (e: any) {
    ElMessage.error(e || t("settings.globalEnv.fetchError"));
  } finally {
    globalEnvLoading.value = false;
  }
}

async function saveGlobalEnv() {
  if (!selectedHost.value) return;
  try {
    await store.saveGlobalEnv(selectedHost.value.host_id, globalEnvContent.value);
    ElMessage.success(t("settings.globalEnv.saveSuccess", { name: selectedHost.value.display_name }));
    globalEnvDialogVisible.value = false;
  } catch (e: any) {
    ElMessage.error(e || t("settings.globalEnv.saveError"));
  }
}

onMounted(() => {
  void loadSettings();
  void store.fetchHosts();
});
</script>

<style scoped>
.settings-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.settings-panel {
  padding: 24px;
}

.settings-tabs :deep(.el-tabs__header) {
  border-bottom: 1px solid var(--border-subtle);
  margin-bottom: 20px;
}

.settings-tabs :deep(.el-tabs__item) {
  font-weight: 600;
  transition: all 0.2s ease;
}

.tab-pane-content {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding-top: 10px;
}

.tab-alert {
  border-radius: 8px;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
  gap: 24px;
}

.input-with-unit {
  display: flex;
  align-items: center;
  gap: 12px;
}

.unit-text {
  font-size: 13px;
  color: var(--text-muted);
  font-weight: 600;
}

.form-help {
  font-size: 12px;
  color: var(--text-muted);
  margin-top: 6px;
  line-height: 1.4;
}

.form-actions-row {
  margin-top: 30px;
  border-top: 1px solid var(--border-subtle);
  padding-top: 20px;
}

/* Tab 3 Hosts */
.pane-header-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.pane-header-kicker {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-secondary);
}

.host-table {
  border-radius: 8px;
  overflow: hidden;
}

/* Stack Icons cell — preview strip + manage button */
.icons-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.icons-preview-strip {
  display: flex;
  align-items: center;
  gap: 3px;
}

.icon-strip-thumb {
  width: 22px;
  height: 22px;
  border-radius: 4px;
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  flex-shrink: 0;
  overflow: hidden;
  display: grid;
  place-items: center;
}

.icon-strip-placeholder {
  font-size: 12px;
  color: var(--text-muted);
}

.icons-more-chip {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-muted);
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  padding: 1px 4px;
  white-space: nowrap;
}

.icons-empty {
  font-size: 13px;
  color: var(--text-muted);
}

.icons-manage-btn {
  flex-shrink: 0;
  background: transparent !important;
  border-color: var(--el-border-color) !important;
  color: var(--el-text-color-secondary) !important;
}

.icons-manage-btn:hover {
  background: var(--el-fill-color-light) !important;
  border-color: var(--el-border-color-hover) !important;
  color: var(--el-text-color-primary) !important;
}

/* Pierce into icon element inside button */
:deep(.icons-manage-btn .el-icon) {
  color: inherit;
}

.url-text {
  font-size: var(--text-md);
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  word-break: break-all;
}

.host-code-text {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-variant-numeric: tabular-nums;
}

.url-text.text-muted {
  line-height: 1.4;
}

.row-operations {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}

/* Dialog Styles */
.dialog-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.mode-radios {
  margin-bottom: 12px;
}

.mode-section {
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 16px;
  margin-top: 12px;
}

.legacy-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.legacy-card {
  background: var(--surface-base);
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 14px;
}

.legacy-card.full-width {
  grid-column: span 2;
}

.legacy-card-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 12px;
  border-left: 3px solid var(--accent-blue);
  padding-left: 8px;
  line-height: 1;
}

.dialog-actions-row {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 16px;
}

.dialog-actions-row .spacer {
  flex: 1;
}

/* Icons Management */
.icons-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.global-env-dialog {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.global-env-textarea :deep(textarea) {
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.55;
}

.mono-input :deep(.el-input__inner) {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.section-kicker {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: 8px;
}

.pattern-code {
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  padding: 2px 6px;
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  color: var(--accent-blue);
}

.font-mono {
  font-family: var(--font-mono);
}

.icon-preview-cell {
  width: 32px;
  height: 32px;
  border-radius: 4px;
  background: var(--surface-panel-raised);
  display: grid;
  place-items: center;
  padding: 2px;
}

.icon-placeholder-cell {
  font-size: 18px;
  color: var(--text-muted);
}

.add-icon-form {
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 16px;
}

.icon-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.local-file-picker {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.file-select {
  flex: 1;
}

.icon-form-action {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

@media (max-width: 768px) {
  .dialog-grid,
  .icon-form-grid,
  .legacy-grid {
    grid-template-columns: 1fr;
  }
  
  :deep(.mobile-hidden) {
    display: none !important;
  }
}
</style>
