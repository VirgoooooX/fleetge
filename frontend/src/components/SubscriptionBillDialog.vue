<template>
  <el-dialog
    v-model="visible"
    title="套餐与账单"
    width="560px"
    class="ui-dialog subscription-bill-dialog"
    destroy-on-close
    append-to-body
  >
    <div v-if="subscription" class="bill-modal-body">
      <!-- Section 1: 基础资费与到期 -->
      <div class="bill-info-list">
        <div class="bill-row">
          <span class="bill-label">服务商</span>
          <span class="bill-value font-medium">{{ subscription.provider || '未填写' }}</span>
        </div>
        <div class="bill-row">
          <span class="bill-label">套餐</span>
          <span class="bill-value font-medium">{{ subscription.plan_name || '自定义配置' }}</span>
        </div>
        <div class="bill-row">
          <span class="bill-label">付款金额</span>
          <span class="bill-value price-text font-bold">
            {{ formatPrice(subscription.payment_amount, subscription.currency, subscription.payment_cycle) }}
          </span>
        </div>
        <div class="bill-row">
          <span class="bill-label">服务到期</span>
          <div class="bill-value-group">
            <span class="bill-value font-mono">{{ subscription.service_expiry_date || '-' }}</span>
            <span v-if="subscription.service_days_remaining != null" class="expiry-pill" :class="getExpiryTone(subscription.service_days_remaining)">
              {{ subscription.service_days_remaining > 0 ? `${subscription.service_days_remaining} 天后到期` : '已到期' }}
            </span>
          </div>
        </div>
        <div class="bill-row">
          <span class="bill-label">自动续费</span>
          <span class="bill-tag" :class="subscription.auto_renew ? 'is-enabled' : 'is-disabled'">
            {{ subscription.auto_renew ? '开启' : '关闭' }}
          </span>
        </div>
      </div>

      <!-- Section 2: 流量套餐与配额 -->
      <div v-if="traffic" class="bill-quota-section">
        <h4 class="quota-title">流量套餐</h4>
        <div class="quota-head">
          <span class="quota-numbers font-mono">
            <strong>{{ formatBytes(traffic.usedBytes) }}</strong> / {{ formatBytes(traffic.quotaBytes) }}
          </span>
          <span class="quota-pct font-mono font-bold">{{ traffic.usagePercent }}%</span>
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
          <span class="quota-meta font-mono">{{ traffic.nextResetText || '每月 1 日重置' }}</span>
        </div>
      </div>

      <!-- Section 3: 告警状态 -->
      <div class="bill-alert-row">
        <div class="alert-left">
          <svg class="alert-bell-icon" xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>
            <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>
          </svg>
          <span>到期与流量告警</span>
        </div>
        <span class="bill-tag is-enabled">已启用</span>
      </div>
    </div>

    <template #footer>
      <div class="bill-modal-footer">
        <el-button @click="handleEdit" class="ui-button">编辑套餐</el-button>
        <el-button type="primary" @click="handleRenew" class="ui-button ui-button--primary">标记已续费</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { ElMessage } from "element-plus";

const props = defineProps<{
  modelValue: boolean;
  hostName: string;
  subscription?: {
    provider?: string;
    plan_name?: string;
    payment_amount?: number;
    currency?: string;
    payment_cycle?: string;
    service_expiry_date?: string;
    service_days_remaining?: number;
    auto_renew?: boolean;
    quota_enabled?: boolean;
    traffic_direction?: string;
  };
  traffic?: {
    usedBytes?: number;
    quotaBytes?: number;
    usagePercent?: number;
    nextResetText?: string;
  };
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

function formatPrice(amount?: number, currency = "CNY", cycle = "annual"): string {
  if (amount == null) return "未设置";
  const sym = currency === "USD" ? "$" : currency === "EUR" ? "€" : "¥";
  const cycleMap: Record<string, string> = {
    monthly: "月",
    quarterly: "季",
    semiannual: "半年",
    annual: "年",
    once: "一次性",
  };
  const cycleText = cycleMap[cycle] || "年";
  return `${sym}${amount.toFixed(2)} / ${cycleText}`;
}

function formatBytes(bytes?: number): string {
  if (bytes == null || isNaN(bytes)) return "0 B";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let val = bytes;
  while (val >= 1024 && i < units.length - 1) {
    val /= 1024;
    i++;
  }
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`;
}

function getExpiryTone(days?: number): string {
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
  const map: Record<string, string> = {
    both: "双向累计计费",
    upload: "仅上行计费",
    download: "仅下行计费",
    max: "单向峰值计费",
  };
  return map[direction || "both"] || "双向累计计费";
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
