<template>
  <el-dialog
    v-model="hostDialogVisible"
    :title="hostFormMode === 'create' ? t('settings.hosts.create') : t('settings.hosts.edit')"
    width="min(760px, calc(100vw - 24px))"
    top="max(12px, 4vh)"
    class="ui-dialog host-editor-dialog"
    :before-close="closeHostDialog"
  >
    <el-scrollbar max-height="calc(100dvh - 160px)" :tabindex="0">
    <el-form class="host-editor-form params-settings-form" :model="hostForm" label-position="top" ref="hostFormRef" :rules="hostRules" v-loading="hostFormLoading">
      <section class="form-cluster">
        <h3 class="cluster-title">{{ t('settings.hosts.form.basic') }}</h3>
        <el-form-item class="settings-field-row" :label="t('settings.hosts.form.id')" prop="host_id">
          <el-input
            class="mono-input"
            v-model="hostForm.host_id"
            :placeholder="t('settings.hosts.form.idPlaceholder')"
            :disabled="hostFormMode === 'edit'"
          />
        </el-form-item>

        <el-form-item class="settings-field-row" :label="t('settings.hosts.form.name')" prop="display_name">
          <el-input v-model="hostForm.display_name" :placeholder="t('settings.hosts.form.namePlaceholder')" />
        </el-form-item>

        <el-form-item class="settings-field-row" :label="t('settings.hosts.form.logo')" prop="logo">
          <div class="host-logo-picker">
            <el-select
              v-model="hostForm.logo"
              clearable
              filterable
              allow-create
              default-first-option
              :placeholder="t('settings.hosts.form.logoPlaceholder')"
              class="host-logo-select"
            >
              <el-option :label="t('settings.hosts.form.logoNone')" value="" />
              <el-option
                v-for="preset in HOST_LOGO_PRESETS"
                :key="preset.key"
                :label="preset.label"
                :value="preset.key"
              >
                <div class="host-logo-option">
                  <img :src="preset.src" :alt="preset.label" class="host-logo-option-img" />
                  <span>{{ preset.label }}</span>
                </div>
              </el-option>
            </el-select>
            <div v-if="selectedFormLogo" class="host-logo-preview" :title="hostForm.logo">
              <img :src="selectedFormLogo.src" alt="" class="host-logo-preview-img" />
            </div>
          </div>
        </el-form-item>

        <el-form-item class="settings-field-row" :label="t('settings.hosts.form.sort')" prop="sort_order">
          <el-input-number v-model="hostForm.sort_order" :min="0" />
        </el-form-item>

        <el-form-item class="settings-field-row" :label="t('settings.hosts.form.enabled')" prop="enabled">
          <el-switch v-model="hostForm.enabled" />
        </el-form-item>
      </section>

      <section class="form-cluster">
        <h3 class="cluster-title">{{ t('settings.hosts.form.connection') }}</h3>
        <el-form-item class="settings-field-row" :label="t('settings.hosts.form.agentUrl')" prop="agent_url">
          <el-input class="mono-input" v-model="hostForm.agent_url" placeholder="http://your-host:8080/fleetge-random-path" />
          <div class="form-help">{{ t("settings.hosts.form.agentUrlHelp") }}</div>
        </el-form-item>
        <el-form-item class="settings-field-row" :label="t('settings.hosts.form.agentToken')" prop="agent_token">
          <el-input
            class="mono-input"
            v-model="hostForm.agent_token"
            type="password"
            show-password
            :placeholder="hostFormMode === 'edit' ? t('settings.hosts.form.unchangedPlaceholder') : t('settings.hosts.form.agentTokenPlaceholder')"
          />
        </el-form-item>
      </section>

      <section class="form-cluster">
        <header class="host-editor-section-header">
          <h3 class="cluster-title">{{ t('settings.hosts.subscription.plan') }}</h3>
          <el-button v-if="hostFormMode === 'edit'" class="ui-button ui-button--compact" @click="openRenewalDialog">{{ t('settings.hosts.renewal.open') }}</el-button>
        </header>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.provider')">
              <el-input v-model="subscriptionForm.provider" />
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.planName')">
              <el-input v-model="subscriptionForm.plan_name" />
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.amount')">
              <div class="subscription-inline-inputs">
                <el-input-number v-model="subscriptionForm.payment_amount" :min="0" :precision="4" :step="1" />
                <el-select v-model="subscriptionForm.currency" class="subscription-currency-select">
                  <el-option v-for="currency in ['CNY', 'USD', 'EUR', 'GBP', 'JPY']" :key="currency" :label="currency" :value="currency" />
                </el-select>
              </div>
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.paymentCycle')">
              <el-select v-model="subscriptionForm.payment_cycle" clearable>
                <el-option v-for="cycle in paymentCycles" :key="cycle.value" :label="t(cycle.label)" :value="cycle.value" />
              </el-select>
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.nextPayment')">
              <el-date-picker v-model="subscriptionForm.next_payment_date" type="date" value-format="YYYY-MM-DD" clearable />
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.expiryDate')">
              <el-date-picker v-model="subscriptionForm.service_expiry_date" type="date" value-format="YYYY-MM-DD" clearable />
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.autoRenew')">
              <el-switch v-model="subscriptionForm.auto_renew" />
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.managementUrl')">
              <el-input v-model="subscriptionForm.management_url" placeholder="https://" />
            </el-form-item>
      </section>

      <section class="form-cluster">
        <h3 class="cluster-title">{{ t('settings.hosts.subscription.trafficAndAlerts') }}</h3>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.quotaEnabled')">
              <el-switch v-model="subscriptionForm.quota_enabled" />
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.quota')">
              <div class="subscription-inline-inputs">
                <el-input-number
                  v-model="subscriptionForm.traffic_quota_value"
                  :min="0.000001"
                  :precision="6"
                  :step="1"
                  :disabled="!subscriptionForm.quota_enabled"
                />
                <el-select v-model="subscriptionForm.traffic_quota_unit" :disabled="!subscriptionForm.quota_enabled" class="subscription-currency-select">
                  <el-option v-for="unit in ['GB', 'TB', 'GiB', 'TiB']" :key="unit" :label="unit" :value="unit" />
                </el-select>
              </div>
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.direction')">
              <el-select v-model="subscriptionForm.traffic_direction" :disabled="!subscriptionForm.quota_enabled">
                <el-option v-for="direction in trafficDirections" :key="direction.value" :label="t(direction.label)" :value="direction.value" />
              </el-select>
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.form.trafficBillingDay')" prop="traffic_billing_day">
              <el-input-number v-model="hostForm.traffic_billing_day" :min="1" :max="31" :step="1" />
              <div class="form-help">{{ t('settings.hosts.form.trafficBillingDayHelp') }}</div>
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.timezone')">
              <el-input v-model="subscriptionForm.billing_timezone" placeholder="Asia/Shanghai" :disabled="!subscriptionForm.quota_enabled" />
            </el-form-item>
            <el-form-item class="settings-field-row" :label="t('settings.hosts.subscription.alertsEnabled')">
              <el-switch v-model="subscriptionForm.alerts_enabled" />
            </el-form-item>
            <el-form-item class="settings-field-row host-editor-notes" :label="t('settings.hosts.subscription.notes')">
              <el-input v-model="subscriptionForm.notes" type="textarea" :rows="2" maxlength="4000" show-word-limit />
            </el-form-item>
        <p class="host-editor-help">{{ t('settings.hosts.subscription.trafficHelp') }}</p>
      </section>
    </el-form>
    </el-scrollbar>

    <template #footer>
      <div class="host-editor-actions">
        <el-button class="ui-button" @click="testFormConnection" :loading="testConnectionLoading">
          {{ t("settings.hosts.action.test") }}
        </el-button>
        <div class="spacer"></div>
        <el-button class="ui-button" @click="closeHostDialog">{{ t('compose.cancel') }}</el-button>
        <el-button class="ui-button" type="primary" @click="saveHostForm" :loading="hostFormLoading" :disabled="hostFormMode === 'edit' && !hostSubscriptionLoaded">{{ t('compose.saveAction') }}</el-button>
      </div>
    </template>
  </el-dialog>

  <HostRenewalDialog
    v-model="renewalDialogVisible"
    :host-id="hostForm.host_id"
    @saved="onRenewalSaved"
  />
</template>

<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useI18n } from "vue-i18n";
import { ElMessage, type FormInstance, type FormRules } from "element-plus";
import { settingsApi, type HostSubscription, type PaymentCycle } from "@/api/settings";
import { apiErrorMessage } from "@/api/errors";
import { useSettingsStore, type HostConfigResponse } from "@/stores/settings";
import { HOST_LOGO_PRESETS, resolveHostLogo } from "@/utils/hostLogo";
import HostRenewalDialog, { type RenewalSavedPayload } from "./HostRenewalDialog.vue";

const { t } = useI18n();
const store = useSettingsStore();

const hostDialogVisible = ref(false);
const hostFormMode = ref<"create" | "edit">("create");
const hostFormLoading = ref(false);
const testConnectionLoading = ref(false);
const hostFormRef = ref<FormInstance>();
const hostSubscriptionLoaded = ref(false);
let hostDialogRequest = 0;
const renewalDialogVisible = ref(false);

const paymentCycles = [
  { value: "monthly", label: "settings.hosts.subscription.cycle.monthly" },
  { value: "quarterly", label: "settings.hosts.subscription.cycle.quarterly" },
  { value: "semiannual", label: "settings.hosts.subscription.cycle.semiannual" },
  { value: "annual", label: "settings.hosts.subscription.cycle.annual" },
  { value: "once", label: "settings.hosts.subscription.cycle.once" },
];
const trafficDirections = [
  { value: "upload", label: "settings.hosts.subscription.direction.upload" },
  { value: "download", label: "settings.hosts.subscription.direction.download" },
  { value: "both", label: "settings.hosts.subscription.direction.both" },
  { value: "max", label: "settings.hosts.subscription.direction.max" },
];
const subscriptionForm = reactive({
  provider: "",
  plan_name: "",
  payment_amount: null as number | null,
  currency: "CNY",
  payment_cycle: null as PaymentCycle | null,
  next_payment_date: "",
  service_expiry_date: "",
  auto_renew: false,
  management_url: "",
  notes: "",
  quota_enabled: false,
  traffic_quota_value: null as number | null,
  traffic_quota_unit: "GiB",
  traffic_direction: "both",
  billing_timezone: "Asia/Shanghai",
  alerts_enabled: true,
});

function resetSubscriptionForm() {
  Object.assign(subscriptionForm, {
    provider: "",
    plan_name: "",
    payment_amount: null,
    currency: "CNY",
    payment_cycle: null,
    next_payment_date: "",
    service_expiry_date: "",
    auto_renew: false,
    management_url: "",
    notes: "",
    quota_enabled: false,
    traffic_quota_value: null,
    traffic_quota_unit: "GiB",
    traffic_direction: "both",
    billing_timezone: "Asia/Shanghai",
    alerts_enabled: true,
  });
}

function applySubscription(data: HostSubscription) {
  Object.assign(subscriptionForm, {
    ...data,
    payment_cycle: data.payment_cycle || null,
    next_payment_date: data.next_payment_date || "",
    service_expiry_date: data.service_expiry_date || "",
    management_url: data.management_url || "",
    notes: data.notes || "",
  });
}

const hostForm = reactive({
  host_id: "",
  display_name: "",
  logo: "",
  enabled: true,
  sort_order: 0,
  traffic_billing_day: 1,
  agent_url: "",
  agent_token: "",
});

const selectedFormLogo = computed(() => resolveHostLogo(hostForm.logo));

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
    { validator: validateHttpUrl, trigger: "blur" },
  ],
});

function openCreateHostDialog() {
  ++hostDialogRequest;
  hostFormLoading.value = false;
  hostFormMode.value = "create";
  hostSubscriptionLoaded.value = true;
  hostForm.host_id = "";
  hostForm.display_name = "";
  hostForm.logo = "";
  hostForm.enabled = true;
  hostForm.sort_order = store.hosts.length > 0 ? Math.max(...store.hosts.map((h) => h.sort_order)) + 10 : 10;
  hostForm.traffic_billing_day = 1;
  hostForm.agent_url = "";
  hostForm.agent_token = "";
  resetSubscriptionForm();
  hostDialogVisible.value = true;
}

async function openEditHostDialog(row: HostConfigResponse) {
  const requestId = ++hostDialogRequest;
  hostFormMode.value = "edit";
  hostForm.host_id = row.host_id;
  hostForm.display_name = row.display_name;
  hostForm.logo = row.logo || "";
  hostForm.enabled = row.enabled;
  hostForm.sort_order = row.sort_order;
  hostForm.traffic_billing_day = row.traffic_billing_day || 1;
  hostForm.agent_url = row.agent_url || "";
  hostForm.agent_token = "";
  resetSubscriptionForm();
  hostSubscriptionLoaded.value = false;
  hostDialogVisible.value = true;
  hostFormLoading.value = true;
  try {
    const data = await settingsApi.fetchSubscription(row.host_id);
    if (requestId !== hostDialogRequest || !hostDialogVisible.value) return;
    applySubscription(data);
    hostSubscriptionLoaded.value = true;
  } catch (err) {
    if (requestId === hostDialogRequest && hostDialogVisible.value) {
      ElMessage.error(apiErrorMessage(err, t("settings.hosts.subscription.loadError")));
    }
  } finally {
    if (requestId === hostDialogRequest) hostFormLoading.value = false;
  }
}

function closeHostDialog() {
  ++hostDialogRequest;
  hostForm.agent_token = "";
  hostFormLoading.value = false;
  renewalDialogVisible.value = false;
  hostDialogVisible.value = false;
  hostFormRef.value?.clearValidate();
}

function prepareHostPayload() {
  return {
    display_name: hostForm.display_name,
    logo: hostForm.logo || "",
    enabled: hostForm.enabled,
    sort_order: hostForm.sort_order,
    traffic_billing_day: hostForm.traffic_billing_day,
    agent_url: hostForm.agent_url,
    agent_token: hostForm.agent_token || (hostFormMode.value === "edit" ? null : ""),
  };
}

async function saveHostForm() {
  if (!hostFormRef.value || hostFormLoading.value || !hostSubscriptionLoaded.value) return;
  const requestId = hostDialogRequest;
  const valid = await hostFormRef.value.validate().then(() => true).catch(() => false);
  if (!valid || requestId !== hostDialogRequest || !hostDialogVisible.value) return;
  if (subscriptionForm.quota_enabled && !subscriptionForm.traffic_quota_value) {
    ElMessage.error(t("settings.hosts.subscription.quotaRequired"));
    return;
  }

  const payload = prepareHostPayload();
  const creating = hostFormMode.value === "create";
  const hostId = hostForm.host_id;
  const subscriptionPayload = {
    ...subscriptionForm,
    payment_cycle: subscriptionForm.payment_cycle || null,
    payment_amount: subscriptionForm.payment_amount,
    next_payment_date: subscriptionForm.next_payment_date || null,
    service_expiry_date: subscriptionForm.service_expiry_date || null,
    management_url: subscriptionForm.management_url || null,
    notes: subscriptionForm.notes || null,
    traffic_quota_value: subscriptionForm.traffic_quota_value,
  };
  hostFormLoading.value = true;
  try {
    if (creating) {
      await store.createHost({ ...payload, host_id: hostId });
      if (requestId === hostDialogRequest) hostFormMode.value = "edit";
    } else {
      await store.updateHost(hostId, payload);
    }
    if (requestId === hostDialogRequest) hostForm.agent_token = "";
    await settingsApi.saveSubscription(hostId, subscriptionPayload);
    if (requestId !== hostDialogRequest || !hostDialogVisible.value) return;
    ElMessage.success(t(creating ? "settings.hosts.create.success" : "settings.hosts.update.success"));
    closeHostDialog();
  } catch (err) {
    if (requestId === hostDialogRequest && hostDialogVisible.value) {
      ElMessage.error(apiErrorMessage(err, t("settings.hosts.save.error")));
    }
  } finally {
    if (requestId === hostDialogRequest) hostFormLoading.value = false;
  }
}

function openRenewalDialog() {
  if (!hostForm.host_id) return;
  renewalDialogVisible.value = true;
}

function onRenewalSaved(data: RenewalSavedPayload) {
  subscriptionForm.next_payment_date = data.paymentDate || "";
  subscriptionForm.service_expiry_date = data.serviceExpiryDate || "";
}

async function testFormConnection() {
  if (!hostFormRef.value || testConnectionLoading.value) return;
  const requestId = hostDialogRequest;
  const valid = await hostFormRef.value.validateField("agent_url").catch(() => false);
  if (!valid || requestId !== hostDialogRequest || !hostDialogVisible.value) return;

  testConnectionLoading.value = true;
  try {
    const res = await store.testNewConnection({ ...prepareHostPayload(), host_id: hostForm.host_id });
    if (requestId !== hostDialogRequest || !hostDialogVisible.value) return;
    if (res.success) {
      ElMessage.success(t("settings.hosts.test.newSuccess", { time: res.response_time_ms, msg: res.message }));
    } else {
      ElMessage.error(t("settings.hosts.test.error", { msg: res.message }));
    }
  } finally {
    testConnectionLoading.value = false;
  }
}

defineExpose({ openCreateHostDialog, openEditHostDialog });
</script>

<style scoped>
.form-help {
  margin-top: 6px;
}

:global(.el-dialog.host-editor-dialog) {
  padding: 0;
  overflow: hidden;
  border-radius: var(--ui-radius-lg);
}

:global(.host-editor-dialog .el-dialog__header) {
  margin: 0;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-subtle);
}

:global(.host-editor-dialog .el-dialog__body) {
  padding: 0;
}

:global(.host-editor-dialog .el-dialog__footer) {
  padding: 12px 20px;
  border-top: 1px solid var(--border-subtle);
}

.host-editor-form {
  display: grid;
  gap: 12px;
  padding: 16px 20px;
}

.host-editor-form .cluster-title {
  padding: 9px 12px;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  text-transform: none;
}

.host-editor-form .settings-field-row {
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr);
  align-items: center;
  gap: 6px 16px;
  padding: 6px 12px;
}

.host-editor-form .settings-field-row :deep(.el-form-item__label) {
  display: block;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  white-space: normal;
}

.host-editor-form .settings-field-row :deep(.el-form-item__content) {
  min-width: 0;
  justify-content: flex-start;
}

.host-editor-form :deep(.el-input),
.host-editor-form :deep(.el-select),
.host-editor-form :deep(.el-date-editor.el-input),
.host-editor-form :deep(.el-textarea) {
  width: 100%;
}

.host-editor-form :deep(.el-input-number) {
  width: 148px;
  max-width: 100%;
}

.host-editor-form .form-help {
  margin-top: 4px;
  font-size: var(--text-xs);
  line-height: 1.5;
}

.host-editor-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-right: 12px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--ui-dashboard-inset-bg);
}

.host-editor-section-header .cluster-title {
  border: 0;
  background: transparent;
}

.subscription-inline-inputs {
  display: flex;
  width: 100%;
  gap: 8px;
}

.subscription-inline-inputs :deep(.el-input-number) {
  flex: 1;
  width: 0;
  min-width: 0;
}

.host-editor-form :deep(.subscription-currency-select) {
  flex: 0 0 88px;
  width: 88px;
}

.host-editor-help {
  margin: 0;
  padding: 9px 12px;
  border-top: 1px solid var(--border-subtle);
  color: var(--text-muted);
  font-size: var(--text-xs);
  line-height: 1.5;
}

.host-editor-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.host-editor-actions .spacer {
  flex: 1;
}

@media (max-width: 600px) {
  .host-editor-form {
    padding: 12px;
  }

  .host-editor-form .settings-field-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .host-editor-form :deep(.el-form-item__label),
  .host-editor-form :deep(.el-form-item__content) {
    grid-column: 1;
  }

  :global(.host-editor-dialog .el-dialog__header),
  :global(.host-editor-dialog .el-dialog__footer) {
    padding: 12px;
  }
}

.mono-input :deep(.el-input__inner) {
  font-family: var(--font-mono);
}

.host-logo-picker {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
}

.host-logo-select {
  flex: 1;
  min-width: 0;
}

.host-logo-preview {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 5px;
  box-sizing: border-box;
  flex-shrink: 0;
}

.host-logo-preview-img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

.host-logo-option {
  display: flex;
  align-items: center;
  gap: 8px;
}

.host-logo-option-img {
  width: 18px;
  height: 18px;
  object-fit: contain;
  flex-shrink: 0;
}
</style>
