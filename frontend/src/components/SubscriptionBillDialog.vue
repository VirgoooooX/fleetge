<template>
  <el-dialog
    v-model="visible"
    :title="t('billing.title')"
    width="min(560px, calc(100vw - 24px))"
    class="ui-dialog subscription-bill-dialog"
    destroy-on-close
    append-to-body
  >
    <div v-if="subscription" class="bill-modal-body">
      <!-- Section 1: 基础资费与到期 -->
      <div class="bill-info-list">
        <div class="bill-row">
          <span class="bill-label">{{ t('settings.hosts.subscription.provider') }}</span>
          <span class="bill-value u-medium">{{ subscription.provider || t('billing.unset') }}</span>
        </div>
        <div class="bill-row">
          <span class="bill-label">{{ t('settings.hosts.subscription.planName') }}</span>
          <span class="bill-value u-medium">{{ subscription.plan_name || t('billing.customPlan') }}</span>
        </div>
        <div class="bill-row">
          <span class="bill-label">{{ t('settings.hosts.subscription.amount') }}</span>
          <span class="bill-value price-text u-bold u-tabular">
            {{ formatSubscriptionPrice(subscription.payment_amount, subscription.currency, subscription.payment_cycle, { fixedDecimals: true }) || t('billing.unset') }}
          </span>
        </div>
        <div class="bill-row">
          <span class="bill-label">{{ t('settings.hosts.subscription.expiryDate') }}</span>
          <div class="bill-value-group">
            <span class="bill-value u-mono u-tabular">{{ subscription.service_expiry_date || '-' }}</span>
            <span v-if="subscription.service_days_remaining != null" class="expiry-pill" :class="getExpiryTone(subscription.service_days_remaining)">
              {{ formatExpiry(subscription.service_days_remaining) }}
            </span>
          </div>
        </div>
        <div class="bill-row">
          <span class="bill-label">{{ t('billing.autoRenew') }}</span>
          <span class="bill-tag" :class="subscription.auto_renew ? 'is-enabled' : 'is-disabled'">
            {{ t(subscription.auto_renew ? 'billing.enabled' : 'billing.disabled') }}
          </span>
        </div>
      </div>

      <!-- Section 2: 流量套餐与配额 -->
      <div v-if="traffic" class="bill-quota-section">
        <h4 class="quota-title">{{ t('billing.quota') }}</h4>
        <div class="quota-head">
          <span class="quota-numbers u-mono u-tabular">
            <strong>{{ formatBytes(traffic.usedBytes) }}</strong> / {{ formatBytes(traffic.quotaBytes) }}
          </span>
          <span class="quota-pct u-mono u-bold u-tabular">{{ traffic.usagePercent }}%</span>
        </div>
        <div class="quota-track">
          <div
            class="quota-fill"
            :style="{
              width: `${Math.min(100, traffic.usagePercent || 0)}%`,
              background: getQuotaColor(traffic.usagePercent || 0)
            }"
          />
        </div>
        <div class="quota-foot">
          <span class="quota-meta">{{ getDirectionText(subscription.traffic_direction) }}</span>
          <span class="quota-meta u-mono u-tabular">{{ formatBillingReset(traffic.nextResetAt, traffic.billingDay, traffic.billingTimezone) }}</span>
        </div>
      </div>

      <!-- Section 3: 告警状态 -->
      <div class="bill-alert-row">
        <div class="alert-left">
          <Bell :size="16" class="alert-bell-icon" aria-hidden="true" />
          <span>{{ t('billing.alerts') }}</span>
        </div>
        <span class="bill-tag" :class="alertsActive ? 'is-enabled' : 'is-disabled'">
          {{ t(alertsActive ? 'billing.enabled' : 'billing.disabled') }}
        </span>
      </div>
    </div>

    <template #footer>
      <div class="bill-modal-footer">
        <el-button @click="handleEdit" class="ui-button">{{ t('billing.edit') }}</el-button>
        <el-button type="primary" @click="handleRenew" class="ui-button ui-button--primary">{{ t('billing.renew') }}</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { formatBillingReset, formatExpiry, formatSubscriptionPrice } from "@/utils/format";
import { Bell } from "@lucide/vue";
import { notifyHubApi } from "@/api/notifyHub";
import type { HostSubscriptionSummary, TrafficQuotaSummary } from "@/stores/dashboard";
import { formatBytes } from "@/utils/formatBytes";

const { t } = useI18n();

const props = defineProps<{
  modelValue: boolean;
  hostName: string;
  subscription?: HostSubscriptionSummary | null;
  traffic?: TrafficQuotaSummary | null;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", value: boolean): void;
  (e: "edit"): void;
  (e: "renew"): void;
}>();

const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit("update:modelValue", val),
});

const globalAlertsEnabled = ref(true);
const alertsActive = computed(
  () => globalAlertsEnabled.value && props.subscription?.alerts_enabled !== false,
);

watch(
  () => props.modelValue,
  async (open, _previous, onCleanup) => {
    if (!open) return;
    const controller = new AbortController();
    onCleanup(() => controller.abort());
    try {
      const enabled = await notifyHubApi.getBillingAlerts(controller.signal);
      if (!controller.signal.aborted) globalAlertsEnabled.value = enabled;
    } catch {
      if (!controller.signal.aborted) globalAlertsEnabled.value = true;
    }
  },
  { immediate: true },
);

function getExpiryTone(days?: number | null): string {
  if (days == null) return "normal";
  if (days <= 0) return "danger";
  if (days <= 7) return "warning";
  return "normal";
}

function getQuotaColor(pct: number): string {
  if (pct >= 90) return "var(--danger, #f87171)";
  if (pct >= 75) return "var(--warning, #fbbf24)";
  return "var(--accent-blue, #3b82f6)";
}

function getDirectionText(direction?: string): string {
  const labels = {
    both: "settings.hosts.subscription.direction.both",
    upload: "settings.hosts.subscription.direction.upload",
    download: "settings.hosts.subscription.direction.download",
    max: "settings.hosts.subscription.direction.max",
  } as const;
  return t(labels[direction as keyof typeof labels] ?? labels.both);
}

function handleEdit() {
  emit("edit");
}

function handleRenew() {
  emit("renew");
  visible.value = false;
}
</script>

<style scoped>
.bill-modal-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 4px 0 12px;
}

.bill-info-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.bill-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  line-height: 1.4;
}

.bill-label {
  color: var(--text-secondary, #94a3b8);
}

.bill-value {
  color: var(--text-primary, #f1f5f9);
}

.bill-value-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.price-text {
  font-size: 16px;
  color: var(--text-primary, #f1f5f9);
}

.expiry-pill {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 99px;
  font-weight: 600;
}
.expiry-pill.normal {
  background: rgba(59, 130, 246, 0.12);
  color: var(--accent-blue, #60a5fa);
}
.expiry-pill.warning {
  background: rgba(251, 191, 36, 0.14);
  color: var(--warning, #fbbf24);
}
.expiry-pill.danger {
  background: rgba(248, 113, 113, 0.14);
  color: var(--danger, #f87171);
}

.bill-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}
.bill-tag.is-enabled {
  background: rgba(52, 211, 153, 0.12);
  color: var(--success, #34d399);
}
.bill-tag.is-disabled {
  background: rgba(148, 163, 184, 0.12);
  color: var(--text-muted, #64748b);
}

/* 流量套餐 */
.bill-quota-section {
  padding-top: 16px;
  border-top: 1px solid var(--border-subtle, rgba(148, 163, 184, 0.12));
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.quota-title {
  margin: 0 0 4px;
  font-size: 14px;
  font-weight: 700;
  color: var(--text-primary, #f1f5f9);
}

.quota-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}

.quota-numbers {
  font-size: 13px;
  color: var(--text-secondary, #94a3b8);
}
.quota-numbers strong {
  font-size: 15px;
  color: var(--text-primary, #f1f5f9);
}

.quota-pct {
  font-size: 14px;
  color: var(--accent-blue, #60a5fa);
}

.quota-track {
  width: 100%;
  height: 6px;
  background: rgba(148, 163, 184, 0.14);
  border-radius: 99px;
  overflow: hidden;
  margin: 2px 0;
}

.quota-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 0.3s ease;
}

.quota-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-muted, #64748b);
}

/* 告警行 */
.bill-alert-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-radius: 8px;
  background: rgba(148, 163, 184, 0.05);
  border: 1px solid var(--border-subtle, rgba(148, 163, 184, 0.12));
}

.alert-left {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-primary, #f1f5f9);
}

.alert-bell-icon {
  color: var(--accent-blue, #60a5fa);
}

.bill-modal-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}
</style>
