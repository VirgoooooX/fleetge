<template>
  <el-dialog v-model="visible" :title="t('settings.appProfiles.title', { name: hostName })" width="min(880px, calc(100vw - 24px))" class="ui-dialog">
    <div v-loading="loading" class="profiles-body">
      <div class="ui-section-kicker">{{ t('settings.appProfiles.existing') }}</div>
      <el-table :data="profiles" stripe size="small" :max-height="profiles.length > 10 ? 460 : undefined">
        <el-table-column :label="t('settings.appProfiles.col.pattern')" prop="stack_pattern" width="130">
          <template #default="{ row }"><code>{{ row.stack_pattern }}</code></template>
        </el-table-column>
        <el-table-column :label="t('settings.appProfiles.col.title')" prop="title" width="130" />
        <el-table-column :label="t('settings.appProfiles.col.url')" prop="app_url" min-width="150" show-overflow-tooltip />
        <el-table-column :label="t('settings.appProfiles.col.group')" width="110" align="center">
          <template #default="{ row }"><el-tag v-if="row.group" size="small">{{ row.group }}</el-tag><span v-else>-</span></template>
        </el-table-column>
        <el-table-column :label="t('settings.appProfiles.col.icon')" width="80" align="center">
          <template #default="{ row }">
            <el-image v-if="profileIcon(row)" :src="iconUrl(profileIcon(row))" class="profile-icon" fit="contain">
              <template #error><el-icon><Picture /></el-icon></template>
            </el-image>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column :label="t('settings.appProfiles.col.actions')" width="98" align="center">
          <template #default="{ row, $index }">
            <div class="row-actions">
              <el-button size="small" type="info" plain :icon="Edit" @click="editProfile(row, $index)" />
              <el-button size="small" type="danger" plain :icon="Delete" @click="removeProfile($index)" />
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-divider>{{ t('settings.appProfiles.addNew') }}</el-divider>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="profile-grid">
          <el-form-item :label="t('settings.appProfiles.form.pattern')" prop="stack_pattern">
            <el-input v-model="form.stack_pattern" :placeholder="t('settings.appProfiles.form.patternPlaceholder')" />
            <div class="form-help" v-html="t('settings.icons.form.patternHelp')"></div>
          </el-form-item>
          <el-form-item :label="t('settings.appProfiles.form.title')" prop="title">
            <el-input v-model="form.title" :placeholder="t('settings.appProfiles.form.titlePlaceholder')" />
          </el-form-item>
          <el-form-item :label="t('settings.appProfiles.form.url')" prop="app_url">
            <el-input v-model="form.app_url" :placeholder="t('settings.appProfiles.form.urlPlaceholder')" />
          </el-form-item>
          <el-form-item :label="t('settings.appProfiles.form.group')" prop="group">
            <el-input v-model="form.group" :placeholder="t('settings.appProfiles.form.groupPlaceholder')" />
          </el-form-item>
          <el-form-item :label="t('settings.appProfiles.form.source')">
            <el-radio-group v-model="form.sourceType" size="small">
              <el-radio-button label="none">{{ t('apps.chip.all') }} (None)</el-radio-button>
              <el-radio-button label="url">{{ t('settings.appProfiles.form.remoteUrl') }}</el-radio-button>
              <el-radio-button label="local">{{ t('settings.appProfiles.form.localFile') }}</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="form.sourceType === 'url'" :label="t('settings.appProfiles.form.remoteUrl')" prop="icon_url">
            <el-input v-model="form.icon_url" placeholder="https://cdn.jsdelivr.net/.../logo.svg" />
          </el-form-item>
          <el-form-item v-else-if="form.sourceType === 'local'" :label="t('settings.appProfiles.form.localFile')">
            <div class="local-picker">
              <el-select v-model="form.icon_file" :placeholder="t('settings.appProfiles.form.localPlaceholder')">
                <el-option v-for="file in availableFiles" :key="file" :label="file" :value="file" />
              </el-select>
              <el-upload action="#" :auto-upload="false" :show-file-list="false" :on-change="uploadIcon">
                <el-button type="info" :icon="Upload" class="ui-button ui-button--muted">{{ t('settings.appProfiles.form.upload') }}</el-button>
              </el-upload>
            </div>
          </el-form-item>
        </div>
        <div class="form-actions">
          <el-button v-if="editingIndex !== null" class="ui-button ui-button--muted" @click="resetForm">{{ t('compose.cancel') }}</el-button>
          <el-button type="primary" class="ui-button ui-button--compact" @click="addProfile">
            {{ editingIndex === null ? t('settings.appProfiles.form.addBtn') : t('settings.appProfiles.form.updateBtn') }}
          </el-button>
        </div>
      </el-form>
    </div>
    <template #footer>
      <div class="dialog-actions-row">
        <el-button @click="visible = false">{{ t('compose.cancel') }}</el-button>
        <el-button type="primary" :loading="store.saving" :disabled="loading" @click="saveProfiles">{{ t('settings.appProfiles.form.saveBtn') }}</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage, type FormInstance, type FormRules, type UploadFile } from "element-plus";
import { Delete, Edit, Picture, Upload } from "@element-plus/icons-vue";
import { useSettingsStore, type AppProfileEntry } from "@/stores/settings";

const props = defineProps<{ hostId: string; hostName: string; stackIcons?: Record<string, string> }>();
const visible = defineModel<boolean>({ required: true });
const emit = defineEmits<{ saved: [] }>();
const { t } = useI18n();
const store = useSettingsStore();
const loading = ref(false);
const profiles = ref<AppProfileEntry[]>([]);
const availableFiles = ref<string[]>([]);
const formRef = ref<FormInstance>();
const editingIndex = ref<number | null>(null);
const emptyForm = () => ({ stack_pattern: "", title: "", app_url: "", group: "", sourceType: "none" as "none" | "url" | "local", icon_url: "", icon_file: "" });
const form = reactive(emptyForm());
const rules: FormRules = {
  stack_pattern: [{ required: true, whitespace: true, message: t("settings.icons.required.pattern"), trigger: "blur" }],
  app_url: [{ validator: (_rule, value, callback) => {
    callback(value && !/^https?:\/\//.test(value.trim()) ? new Error(t("settings.hosts.form.invalid.url")) : undefined);
  }, trigger: "blur" }],
  icon_url: [{ validator: (_rule, value, callback) => {
    callback(value && !/^(https?:\/\/|\/)/.test(value.trim()) ? new Error(t("settings.hosts.form.invalid.url")) : undefined);
  }, trigger: "blur" }],
};

onMounted(async () => {
  loading.value = true;
  try {
    const res = await store.fetchAppProfiles(props.hostId);
    profiles.value = (res.profiles || []).map((row) => {
      const legacy = row as AppProfileEntry & { icon?: string; icon_url?: string; icon_file?: string };
      return { ...row, icon_value: row.icon_value || legacy.icon_url || legacy.icon_file || legacy.icon || null };
    });
    availableFiles.value = res.available_files || [];
  } catch (error: any) {
    ElMessage.error(error || t("settings.appProfiles.fetchError"));
  } finally {
    loading.value = false;
  }
});

function iconUrl(value: string | null): string {
  if (!value) return "";
  return /^(https?:\/\/|\/)/.test(value) ? value : `/api/static/icons/${value}`;
}

function profileIcon(row: AppProfileEntry): string | null {
  if (row.icon_value) return row.icon_value;
  const mapping = props.stackIcons || {};
  if (mapping[row.stack_pattern]) return mapping[row.stack_pattern];
  for (const [key, value] of Object.entries(mapping)) {
    if (key.endsWith("*") && !key.startsWith("*") && row.stack_pattern.startsWith(key.slice(0, -1))) return value;
  }
  for (const [key, value] of Object.entries(mapping)) {
    if (key.startsWith("*") && !key.endsWith("*") && row.stack_pattern.endsWith(key.slice(1))) return value;
  }
  return null;
}

function resetForm() {
  Object.assign(form, emptyForm());
  editingIndex.value = null;
  formRef.value?.clearValidate();
}

function editProfile(row: AppProfileEntry, index: number) {
  resetForm();
  editingIndex.value = index;
  Object.assign(form, { stack_pattern: row.stack_pattern, title: row.title || "", app_url: row.app_url || "", group: row.group || "" });
  if (row.icon_value) {
    form.sourceType = /^(https?:\/\/|\/)/.test(row.icon_value) ? "url" : "local";
    form[form.sourceType === "url" ? "icon_url" : "icon_file"] = row.icon_value;
  }
}

function removeProfile(index: number) {
  profiles.value.splice(index, 1);
  if (editingIndex.value === index) resetForm();
  else if (editingIndex.value !== null && editingIndex.value > index) editingIndex.value--;
}

async function uploadIcon(uploadFile: UploadFile) {
  const file = uploadFile.raw;
  if (!file) return;
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.error(t("settings.icons.upload.tooLarge"));
    return;
  }
  const message = ElMessage({ message: t("settings.icons.upload.progress"), duration: 0, type: "info" });
  try {
    const filename = await store.uploadIcon(props.hostId, file);
    if (!availableFiles.value.includes(filename)) {
      availableFiles.value.push(filename);
      availableFiles.value.sort();
    }
    form.icon_file = filename;
    ElMessage.success(t("settings.icons.upload.success", { name: filename }));
  } catch (error: any) {
    ElMessage.error(error || t("settings.icons.upload.error"));
  } finally {
    message.close();
  }
}

async function addProfile() {
  if (!await formRef.value?.validate().catch(() => false)) return;
  let icon: string | null = null;
  if (form.sourceType === "url") {
    icon = form.icon_url.trim();
    if (!icon) { ElMessage.error(t("settings.icons.required.url")); return; }
  } else if (form.sourceType === "local") {
    icon = form.icon_file;
    if (!icon) { ElMessage.error(t("settings.icons.required.file")); return; }
  }
  const entry: AppProfileEntry = {
    stack_pattern: form.stack_pattern.trim(), title: form.title.trim() || null,
    app_url: form.app_url.trim() || null, group: form.group.trim() || null, icon_value: icon,
  };
  const duplicate = profiles.value.findIndex((item) => item.stack_pattern === entry.stack_pattern);
  const index = editingIndex.value;
  if (duplicate !== -1) {
    profiles.value[duplicate] = entry;
    if (index !== null && index !== duplicate) profiles.value.splice(index, 1);
  } else if (index !== null) profiles.value[index] = entry;
  else profiles.value.push(entry);
  resetForm();
}

async function saveProfiles() {
  try {
    await store.saveAppProfiles(props.hostId, profiles.value);
    ElMessage.success(t("settings.appProfiles.saveSuccess", { name: props.hostName }));
    visible.value = false;
    emit("saved");
  } catch (error: any) {
    ElMessage.error(error || t("settings.appProfiles.saveError"));
  }
}
</script>

<style scoped>
.profiles-body { display: flex; flex-direction: column; gap: 10px; }
.profile-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.profile-grid :deep(.el-form-item) { margin-bottom: 14px; }
.form-help { margin-top: 4px; color: var(--text-muted); font-size: 12px; line-height: 1.5; }
.local-picker { display: flex; align-items: center; gap: 8px; width: 100%; }
.local-picker .el-select { flex: 1; min-width: 0; }
.form-actions, .dialog-actions-row { display: flex; justify-content: flex-end; gap: 8px; }
.profile-icon { width: 32px; height: 32px; padding: 2px; border: 1px solid var(--border-subtle); border-radius: 4px; background: var(--surface-panel-raised); }
.row-actions { display: flex; justify-content: center; gap: 4px; }
.row-actions :deep(.el-button) { width: 28px; height: 28px; padding: 0; margin-left: 0; }
@media (max-width: 768px) { .profile-grid { grid-template-columns: minmax(0, 1fr); } }
</style>
