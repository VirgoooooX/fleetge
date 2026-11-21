<template>
  <section class="wan-capsule" :class="{ 'is-quota': hasQuota, 'is-unmetered': !hasQuota }">
    <div class="capsule-header">
      <div class="capsule-title">
        <Globe :size="13" class="capsule-globe-icon" aria-hidden="true" />
        <span>{{ t(hasQuota ? 'hostCard.wanQuota' : 'hostDetail.network') }}</span>
      </div>

      <div
        class="stream-anchored u-mono u-tabular"
        :title="t('hostCard.liveRates', { rx: `${rxRate.val} ${rxRate.unit}`, tx: `${txRate.val} ${txRate.unit}` })"
      >
        <span class="anchored-label">
          <span class="label-text">{{ t('traffic.live') }}</span>
        </span>

        <span class="col-indicator rx">
          <span class="indicator-glyph" aria-hidden="true">
            <ArrowDown :size="12" :stroke-width="1.8" />
          </span>
        </span>

        <span class="col-num rx">{{ rxRate.val }}</span>

        <span class="col-unit rx">{{ rxRate.unit }}</span>

        <span class="speed-sep" aria-hidden="true" />

        <span class="col-indicator tx">
          <span class="indicator-glyph" aria-hidden="true">
            <ArrowUp :size="12" :stroke-width="1.8" />
          </span>
        </span>

        <span class="col-num tx">{{ txRate.val }}</span>

        <span class="col-unit tx">{{ txRate.unit }}</span>
      </div>
    </div>

    <div v-if="hasQuota" class="capsule-quota-rail">
      <div class="quota-rail-info u-mono u-tabular">
        <span class="quota-ratio">{{ t('hostCard.usedQuota', { used: formatBytes(quotaUsedBytes), total: formatBytes(quotaTotalBytes), percent: quotaUsagePercent }) }}</span>
        <span
          class="quota-remain"
          :class="{
            'is-warn': quotaUsagePercent >= 70 && quotaUsagePercent < 85,
            'is-danger': quotaUsagePercent >= 85
          }"
        >
          {{ t('hostCard.remainingQuota', { remaining: formatBytes(quotaRemainingBytes) }) }}
        </span>
      </div>
      <div class="capsule-progress-track">
        <div
          class="capsule-progress-fill"
          :style="{
            width: `${Math.min(100, quotaUsagePercent)}%`,
            minWidth: quotaUsedBytes > 0 ? '4.5px' : '0',
            background: getQuotaColor(quotaUsagePercent)
          }"
        />
      </div>
    </div>

    <div class="capsule-traffic-matrix">
      <div class="traffic-row">
        <div class="traffic-row-left">
          <span class="scope-label">{{ t(hasQuota ? 'traffic.billingCycle' : 'traffic.month') }}</span>
          <span class="total-vol-slot u-mono u-tabular">
            <strong class="total-num">{{ splitBytes(hasQuota ? quotaUsedBytes : effectiveTrafficMonthTotal).val }}</strong>
            <span class="total-unit">{{ splitBytes(hasQuota ? quotaUsedBytes : effectiveTrafficMonthTotal).unit }}</span>
          </span>
          <template v-if="hasQuota">
            <span class="meta-dot" aria-hidden="true" />
            <span class="reset-tag" :title="effectiveNextResetText">{{ effectiveNextResetText }}</span>
          </template>
        </div>

        <div class="traffic-row-right stream-columns u-mono u-tabular">
          <span class="col-indicator rx" />
          <span class="col-num rx">{{ splitBytes(effectiveTrafficMonthRx).val }}</span>
          <span class="col-unit rx">{{ splitBytes(effectiveTrafficMonthRx).unit }}</span>
          <span class="col-sep" aria-hidden="true" />
          <span class="col-indicator tx" />
          <span class="col-num tx">{{ splitBytes(effectiveTrafficMonthTx).val }}</span>
          <span class="col-unit tx">{{ splitBytes(effectiveTrafficMonthTx).unit }}</span>
        </div>
      </div>

      <div class="traffic-row">
        <div class="traffic-row-left">
          <span class="scope-label">{{ t('traffic.today') }}</span>
          <span class="total-vol-slot u-mono u-tabular">
            <strong class="total-num">{{ splitBytes(effectiveTrafficTodayTotal).val }}</strong>
            <span class="total-unit">{{ splitBytes(effectiveTrafficTodayTotal).unit }}</span>
          </span>
        </div>

        <div class="traffic-row-right stream-columns u-mono u-tabular">
          <span class="col-indicator rx" />
          <span class="col-num rx">{{ splitBytes(effectiveTrafficTodayRx).val }}</span>
          <span class="col-unit rx">{{ splitBytes(effectiveTrafficTodayRx).unit }}</span>
          <span class="col-sep" aria-hidden="true" />
          <span class="col-indicator tx" />
          <span class="col-num tx">{{ splitBytes(effectiveTrafficTodayTx).val }}</span>
          <span class="col-unit tx">{{ splitBytes(effectiveTrafficTodayTx).unit }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import { ArrowDown, ArrowUp, Globe } from "@lucide/vue";
import type { HostSummary, HostSubscriptionSummary, HostTrafficState, TrafficQuotaSummary } from "@/stores/dashboard";
import { formatBillingReset } from "@/utils/format";
import { formatBytes, splitBytes, splitRate } from "@/utils/formatBytes";

export type HostQuotaOverride = Partial<Pick<TrafficQuotaSummary, "usedBytes" | "quotaBytes" | "remainingBytes" | "usagePercent" | "nextResetText" | "nextResetAt" | "billingTimezone" | "billingDay" | "rxBytes" | "txBytes">>;

const props = defineProps<{
  host: HostSummary;
  traffic?: HostTrafficState;
  quota?: HostQuotaOverride;
  subscription?: HostSubscriptionSummary | null;
}>();
const { t } = useI18n();
const effectiveSubscription = computed(() => props.subscription);
const rxRate = computed(() => splitRate(props.host.metrics?.networkRxRate));
const txRate = computed(() => splitRate(props.host.metrics?.networkTxRate));

const effectiveTrafficMonthTotal = computed(() => {
  if (hasQuota.value && (props.quota?.usedBytes != null || props.traffic?.summary?.quota?.usedBytes != null)) {
    return props.quota?.usedBytes ?? props.traffic?.summary?.quota?.usedBytes ?? 0;
  }
  return props.traffic?.summary?.month?.totalBytes ?? 0;
});

const effectiveTrafficMonthRx = computed(() => {
  if (hasQuota.value && (props.quota?.rxBytes != null || props.traffic?.summary?.quota?.rxBytes != null)) {
    return props.quota?.rxBytes ?? props.traffic?.summary?.quota?.rxBytes ?? 0;
  }
  return props.traffic?.summary?.month?.rxBytes ?? 0;
});

const effectiveTrafficMonthTx = computed(() => {
  if (hasQuota.value && (props.quota?.txBytes != null || props.traffic?.summary?.quota?.txBytes != null)) {
    return props.quota?.txBytes ?? props.traffic?.summary?.quota?.txBytes ?? 0;
  }
  return props.traffic?.summary?.month?.txBytes ?? 0;
});

const effectiveTrafficTodayTotal = computed(() => {
  return props.traffic?.summary?.today?.totalBytes ?? 0;
});

const effectiveTrafficTodayRx = computed(() => {
  return props.traffic?.summary?.today?.rxBytes ?? 0;
});

const effectiveTrafficTodayTx = computed(() => {
  return props.traffic?.summary?.today?.txBytes ?? 0;
});

const hasQuota = computed(() => {
  if (props.quota?.quotaBytes) return true;
  if (props.traffic?.summary?.quota?.quotaBytes) return true;
  const sub = effectiveSubscription.value;
  if (sub?.quota_enabled && (sub.traffic_quota_bytes || sub.traffic_quota_value)) return true;
  return false;
});

const quotaTotalBytes = computed(() => {
  if (props.quota?.quotaBytes) return props.quota.quotaBytes;
  if (props.traffic?.summary?.quota?.quotaBytes) return props.traffic.summary.quota.quotaBytes;
  return effectiveSubscription.value?.traffic_quota_bytes ?? 0;
});

const quotaUsedBytes = computed(() => {
  if (props.quota?.usedBytes != null) return props.quota.usedBytes;
  if (props.traffic?.summary?.quota?.usedBytes != null) return props.traffic.summary.quota.usedBytes;
  return effectiveTrafficMonthTotal.value;
});

const quotaRemainingBytes = computed(() => {
  if (props.quota?.remainingBytes != null) return props.quota.remainingBytes;
  if (props.traffic?.summary?.quota?.remainingBytes != null) return props.traffic.summary.quota.remainingBytes;
  return Math.max(0, quotaTotalBytes.value - quotaUsedBytes.value);
});

const quotaUsagePercent = computed(() => {
  if (props.quota?.usagePercent != null) return props.quota.usagePercent;
  if (props.traffic?.summary?.quota?.usagePercent != null) return props.traffic.summary.quota.usagePercent;
  if (!quotaTotalBytes.value) return 0;
  return Math.round((quotaUsedBytes.value / quotaTotalBytes.value) * 1000) / 10;
});

const effectiveNextResetText = computed(() => {
  const summary = props.traffic?.summary?.quota;
  const override = props.quota;
  if (override?.nextResetText) return override.nextResetText;
  return formatBillingReset(
    override?.nextResetAt ?? summary?.nextResetAt,
    override?.billingDay ?? summary?.billingDay ?? props.host.traffic_billing_day,
    override?.billingTimezone ?? summary?.billingTimezone,
  );
});

function getQuotaColor(pct: number): string {
  if (pct >= 85) return "var(--quota-danger-grad)";
  if (pct >= 70) return "var(--quota-warn-grad)";
  return "var(--quota-healthy-grad)";
}
</script>

<style scoped>
/* 一体化 WAN 态势舱 */
.wan-capsule {
  --stream-columns: 12px 34px 34px 10px 12px 34px 34px;
  --quota-healthy-grad: linear-gradient(90deg, #10b981, #22d3ee);
  --quota-warn-grad: linear-gradient(90deg, #f59e0b, #fbbf24);
  --quota-danger-grad: linear-gradient(90deg, #f87171, #ef4444);
  background: rgba(148, 163, 184, 0.04);
  border: 1px solid var(--border-subtle, rgba(148, 163, 184, 0.12));
  border-radius: 8px;
  padding: 9px 11px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.capsule-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 18px;
  font-size: 13px;
}

.capsule-title {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 6px;
  color: var(--text-secondary, #94a3b8);
  font-weight: 600;
}

.capsule-title > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transform: translateY(-0.5px);
}

.capsule-globe-icon {
  display: block;
  flex-shrink: 0;
  color: var(--accent-cyan, #22d3ee);
  width: 14px;
  height: 14px;
}

/* 统一双通道流矩阵（顶栏独占箭头，下方两行去箭头，中缝线绝对贯通） */
.stream-columns {
  display: inline-grid;
  grid-template-columns: var(--stream-columns);
  align-items: center;
  font-size: 12px;
}

/* ── 核心：绝对位置锚定流矩阵 (Strictly Anchored Stream Grid) ── */
/* 8 槽固定列宽：
   col 1: 实时标签 (38px, 左对齐，严丝合缝)
   col 2: 下行箭头 (12px, 居中)
   col 3: 下行数值 (34px, 右对齐 tabular-nums)
   col 4: 下行单位 (34px, 左对齐，容纳 MB/s)
   col 5: 隔离中点 (10px, 居中)
   col 6: 上行箭头 (12px, 居中)
   col 7: 上行数值 (34px, 右对齐 tabular-nums)
   col 8: 上行单位 (34px, 左对齐，容纳 MB/s)
   总宽度固定 208px，右侧贴齐，左侧坐标绝对锁死，0 像素水平抖动！
*/
.stream-anchored {
  display: inline-grid;
  grid-template-columns: 38px var(--stream-columns);
  align-items: center;
  justify-items: stretch;
  width: 208px;
  flex-shrink: 0;
  user-select: none;
}

.stream-anchored .anchored-label {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted, #94a3b8);
  white-space: nowrap;
}

.stream-anchored .col-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
}

.stream-anchored .indicator-glyph {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  border-radius: 50%;
}

.stream-anchored .indicator-glyph svg {
  display: block;
  width: 10px;
  height: 10px;
}

.stream-anchored .col-indicator.rx .indicator-glyph {
  background: rgba(34, 211, 238, 0.12);
  color: var(--accent-cyan, #22d3ee);
}
.stream-anchored .col-indicator.tx .indicator-glyph {
  background: rgba(96, 165, 250, 0.12);
  color: var(--accent-blue, #60a5fa);
}

.stream-anchored .col-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 650;
}
.stream-anchored .col-num.rx {
  color: var(--accent-cyan, #22d3ee);
}
.stream-anchored .col-num.tx {
  color: var(--accent-blue, #60a5fa);
}

.stream-anchored .col-unit {
  text-align: left;
  padding-left: 2px;
  opacity: 0.85;
}
.stream-anchored .col-unit.rx {
  color: var(--accent-cyan, #22d3ee);
}
.stream-anchored .col-unit.tx {
  color: var(--accent-blue, #60a5fa);
}

.stream-anchored .speed-sep {
  display: grid;
  place-items: center;
  opacity: 0.35;
  color: var(--text-muted, #94a3b8);
}

.speed-sep::before,
.meta-dot::before {
  content: "";
  width: 2px;
  height: 2px;
  border-radius: 50%;
  background: currentColor;
}

/* 浅色模式适配 */
[data-theme="light"] .stream-anchored .col-num.rx,
[data-theme="light"] .stream-anchored .col-unit.rx {
  color: #0a6c82;
}
[data-theme="light"] .stream-anchored .col-num.tx,
[data-theme="light"] .stream-anchored .col-unit.tx {
  color: #2563eb;
}
[data-theme="light"] .stream-anchored .col-indicator.rx .indicator-glyph {
  background: rgba(10, 108, 130, 0.1);
  color: #0a6c82;
}
[data-theme="light"] .stream-anchored .col-indicator.tx .indicator-glyph {
  background: rgba(37, 99, 235, 0.1);
  color: #2563eb;
}

.col-indicator {
  text-align: center;
  font-weight: 700;
  line-height: 1;
}
.col-indicator.rx { color: var(--accent-cyan, #22d3ee); }
.col-indicator.tx { color: var(--accent-blue, #60a5fa); }

.col-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.capsule-header .col-num.rx { color: var(--accent-cyan, #22d3ee); }
.capsule-header .col-num.tx { color: var(--accent-blue, #60a5fa); }

/* 下方行如果染色：采用微柔和或全染测试 */
.traffic-row-right .col-num.rx { color: var(--accent-cyan, #22d3ee); }
.traffic-row-right .col-num.tx { color: var(--accent-blue, #60a5fa); }

.col-unit {
  text-align: right; /* 统一右对齐：顶栏 /s 贴右，下方 B 贴右 */
  color: var(--text-muted, #94a3b8);
}
.capsule-header .col-unit.rx { color: var(--accent-cyan, #22d3ee); opacity: 0.85; }
.capsule-header .col-unit.tx { color: var(--accent-blue, #60a5fa); opacity: 0.85; }
.traffic-row-right .col-unit.rx { color: var(--accent-cyan, #22d3ee); opacity: 0.75; }
.traffic-row-right .col-unit.tx { color: var(--accent-blue, #60a5fa); opacity: 0.75; }

.col-sep {
  display: grid;
  place-items: center;
  color: var(--border-subtle, rgba(148, 163, 184, 0.35));
}

.col-sep::before {
  content: "";
  width: 1px;
  height: 10px;
  background: currentColor;
}

/* 配额水位轨 */
.capsule-quota-rail {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.quota-rail-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 8px;
  font-size: 12px;
  color: var(--text-muted, #64748b);
}

.quota-remain.is-warn {
  color: var(--warning, #fbbf24);
  font-weight: 600;
}

.quota-remain.is-danger {
  color: var(--danger, #f87171);
  font-weight: 700;
}

.capsule-progress-track {
  width: 100%;
  height: 4.5px;
  background: rgba(148, 163, 184, 0.14);
  border-radius: 99px;
  overflow: hidden;
}

.capsule-progress-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1), background 0.4s ease;
}

/* 流量矩阵 */
.capsule-traffic-matrix {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.traffic-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 18px;
  font-size: 12px;
}

/* 所有流量文字使用同一种裁剪规则；容器对齐裁剪后的字形盒。 */
.wan-capsule :is(.label-text, .scope-label, .total-num, .total-unit, .col-num, .col-unit, .quota-ratio, .quota-remain) {
  text-box: trim-both cap alphabetic;
  white-space: nowrap;
}

/* 总量、下载、上传及单位统一字号，避免左右两套字高。 */
.wan-capsule :is(.total-num, .total-unit, .col-num, .col-unit) {
  font-size: 12px;
}

/* 中文字形越过拉丁大写边界，统一补偿其可见中心。 */
.wan-capsule :is(.label-text, .scope-label, .quota-remain) {
  transform: translateY(0.25px);
}

/* “/” 的下伸部分也计入可见中心，网速单位和配额说明需向上补偿。 */
.stream-anchored .col-unit {
  transform: translateY(-0.5px);
}

.quota-ratio {
  transform: translateY(-0.25px);
}

.traffic-row-left {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  color: var(--text-muted, #64748b);
}

.traffic-row-right {
  flex-shrink: 0;
}

.scope-label {
  display: inline-block;
  width: 42px;
  flex-shrink: 0;
  color: var(--text-secondary, #94a3b8);
  font-weight: 500;
}

.total-vol-slot {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
}

.total-num {
  min-width: 30px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--text-primary, #f1f5f9);
}

.total-unit {
  width: 24px;
  text-align: right; /* "B" 严格右对齐锚定 */
  color: var(--text-muted, #94a3b8);
  margin-left: 2px;
}

.meta-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin: 0 4px;
  opacity: 0.45;
}

.reset-tag {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted, #64748b);
  font-size: 11px;
}

[data-theme="light"] .wan-capsule {
  --quota-healthy-grad: linear-gradient(90deg, #059669, #0891b2);
  --quota-warn-grad: linear-gradient(90deg, #d97706, #f59e0b);
  --quota-danger-grad: linear-gradient(90deg, #dc2626, #ef4444);
}

[data-theme="light"] .capsule-globe-icon {
  color: #0a6c82;
}
[data-theme="light"] .total-num,
[data-theme="light"] .col-num {
  color: #0f172a;
}
[data-theme="light"] .col-indicator.rx,
[data-theme="light"] .capsule-header .col-num.rx,
[data-theme="light"] .traffic-row-right .col-num.rx {
  color: #0a6c82;
  font-weight: 700;
}
[data-theme="light"] .capsule-header .col-unit.rx,
[data-theme="light"] .traffic-row-right .col-unit.rx {
  color: #0a6c82;
  opacity: 1;
  font-weight: 600;
}
[data-theme="light"] .col-indicator.tx,
[data-theme="light"] .capsule-header .col-num.tx,
[data-theme="light"] .traffic-row-right .col-num.tx {
  color: #1d4ed8;
  font-weight: 700;
}
[data-theme="light"] .capsule-header .col-unit.tx,
[data-theme="light"] .traffic-row-right .col-unit.tx {
  color: #1d4ed8;
  opacity: 1;
  font-weight: 600;
}

[data-theme="light"] .wan-capsule {
  background: rgba(241, 245, 249, 0.45);
  border-color: rgba(226, 232, 240, 0.85);
}
</style>
