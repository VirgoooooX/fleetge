<template>
  <section
    class="traffic-strip"
    :class="`traffic-strip--${variant}`"
    :aria-label="t('traffic.title')"
    :aria-busy="traffic?.loading || undefined"
  >
    <header class="traffic-strip__header">
      <div class="traffic-strip__identity">
        <span class="traffic-strip__activity" :class="activityLevel" />
        <strong>{{ t("hostDetail.network") }}</strong>
        <span
          v-if="networkInterfaceSummary"
          class="traffic-strip__interface"
          :title="networkInterfaceTitle"
        >
          · {{ networkInterfaceSummary }}
        </span>
      </div>
      <div class="traffic-strip__context">
        <div
          class="traffic-strip__cycle-total"
          :title="`${billingCycleLabel} ${t('traffic.total')} ${monthTotal.text} · ${billingCycleTitle}`"
        >
          <span>{{ t("traffic.total") }}</span>
          <strong>{{ monthTotal.amount }}</strong>
          <small>{{ monthTotal.unit }}</small>
        </div>
      </div>
    </header>

    <div class="traffic-strip__values">
      <article
        v-for="segment in trafficSegments"
        :key="segment.key"
        class="traffic-strip__segment"
      >
        <div class="traffic-strip__segment-title" :title="segment.title">
          <span>{{ segment.label }}</span>
        </div>
        <div class="traffic-strip__rows">
          <div class="traffic-strip__row">
            <span class="traffic-strip__arrow is-down">↓</span>
            <strong>{{ segment.rx.amount }}</strong>
            <small>{{ segment.rx.unit }}</small>
          </div>
          <div class="traffic-strip__row">
            <span class="traffic-strip__arrow is-up">↑</span>
            <strong>{{ segment.tx.amount }}</strong>
            <small>{{ segment.tx.unit }}</small>
          </div>
        </div>
      </article>
    </div>

    <svg
      v-if="variant === 'card' && trendPaths.stroke"
      class="traffic-strip__trend"
      width="100%"
      height="18"
      viewBox="0 0 100 18"
      preserveAspectRatio="none"
      shape-rendering="geometricPrecision"
      aria-hidden="true"
    >
      <defs>
        <linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="var(--accent-cyan)" stop-opacity="0.12" />
          <stop offset="100%" stop-color="var(--accent-cyan)" stop-opacity="0" />
        </linearGradient>
      </defs>
      <path :d="trendPaths.fill" :fill="`url(#${gradientId})`" />
      <path
        :d="trendPaths.stroke"
        fill="none"
        stroke="var(--accent-cyan)"
        stroke-width="1"
        stroke-opacity="0.78"
        stroke-linecap="round"
        stroke-linejoin="round"
        vector-effect="non-scaling-stroke"
      />
    </svg>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import type { HostSummary, HostTrafficState } from "@/stores/dashboard";

interface ValueParts {
  amount: string;
  unit: string;
  text: string;
}

interface TrafficSegment {
  key: "live" | "today" | "month";
  label: string;
  title?: string;
  rx: ValueParts;
  tx: ValueParts;
}

const props = withDefaults(defineProps<{
  hostId: string;
  metrics?: HostSummary["metrics"];
  traffic?: HostTrafficState;
  variant?: "card" | "detail";
}>(), {
  metrics: undefined,
  traffic: undefined,
  variant: "card",
});

const { t } = useI18n();
const rateHistory = ref<number[]>([]);
const lastMetricKey = ref("");

const summary = computed(() => props.traffic?.summary || null);
const today = computed(() => summary.value?.today?.hasData ? summary.value.today : null);
const month = computed(() => summary.value?.month?.hasData ? summary.value.month : null);
const liveRx = computed(() => formatParts(props.metrics?.networkRxRate, true));
const liveTx = computed(() => formatParts(props.metrics?.networkTxRate, true));
const todayRx = computed(() => formatParts(today.value?.rxBytes));
const todayTx = computed(() => formatParts(today.value?.txBytes));
const monthRx = computed(() => formatParts(month.value?.rxBytes));
const monthTx = computed(() => formatParts(month.value?.txBytes));
const monthTotal = computed(() => formatParts(month.value?.totalBytes));
const billingDay = computed(() => Math.min(31, Math.max(1, summary.value?.billingDay || 1)));
const billingCycleLabel = computed(() => (
  billingDay.value === 1 ? t("traffic.month") : t("traffic.billingCycle")
));
const billingCycleTitle = computed(() => (
  billingDay.value === 1 ? t("traffic.month") : t("traffic.billingCycleStarts", { day: billingDay.value })
));
const trafficSegments = computed<TrafficSegment[]>(() => [
  {
    key: "live",
    label: t("traffic.live"),
    rx: liveRx.value,
    tx: liveTx.value,
  },
  {
    key: "today",
    label: t("traffic.today"),
    rx: todayRx.value,
    tx: todayTx.value,
  },
  {
    key: "month",
    label: billingCycleLabel.value,
    title: billingCycleTitle.value,
    rx: monthRx.value,
    tx: monthTx.value,
  },
]);
const activityLevel = computed(() => {
  const rate = (props.metrics?.networkRxRate || 0) + (props.metrics?.networkTxRate || 0);
  if (rate >= 10 * 1024 * 1024) return "is-busy";
  if (rate >= 512 * 1024) return "is-active";
  if (rate > 0) return "is-low";
  return "is-idle";
});
const networkInterfaces = computed(() => (
  (props.metrics?.networkInterfaces || []).filter((name) => Boolean(name))
));
const networkInterfaceSummary = computed(() => {
  const interfaces = networkInterfaces.value;
  if (!interfaces.length) return "";
  return interfaces.length === 1 ? interfaces[0] : `${interfaces[0]} +${interfaces.length - 1}`;
});
const networkInterfaceTitle = computed(() => networkInterfaces.value.join(", "));
const gradientId = computed(() => (
  `traffic-${props.hostId}-${props.variant}`.replace(/[^a-zA-Z0-9_-]/g, "-")
));

watch(
  () => props.metrics,
  (metrics) => {
    if (!metrics) return;
    const key = `${metrics.timestamp}|${metrics.networkCounterEpoch || "legacy"}`;
    if (key === lastMetricKey.value) return;
    lastMetricKey.value = key;
    rateHistory.value.push((metrics.networkRxRate || 0) + (metrics.networkTxRate || 0));
    if (rateHistory.value.length > 50) rateHistory.value.shift();
  },
  { immediate: true, deep: true },
);

function formatParts(value: number | null | undefined, perSecond = false): ValueParts {
  if (value == null) return { amount: "—", unit: "", text: "—" };
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let size = Math.max(0, value);
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  const digits = index === 0 ? 0 : size >= 100 ? 0 : size >= 10 ? 1 : 2;
  const amount = size.toFixed(digits);
  const unit = `${units[index]}${perSecond ? "/s" : ""}`;
  return { amount, unit, text: `${amount} ${unit}` };
}

function generateTrend(data: number[]) {
  if (data.length < 6) return { stroke: "", fill: "" };
  const width = 100;
  const height = 18;
  const max = Math.max(...data, 1);
  const points = data.map((value, index) => ({
    x: (index / (data.length - 1)) * width,
    y: 2 + (height - 4) * (1 - value / max),
  }));
  const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));
  let stroke = `M ${points[0].x.toFixed(1)} ${points[0].y.toFixed(1)}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const p0 = points[Math.max(0, index - 1)];
    const p1 = points[index];
    const p2 = points[index + 1];
    const p3 = points[Math.min(points.length - 1, index + 2)];
    const minY = Math.min(p1.y, p2.y);
    const maxY = Math.max(p1.y, p2.y);
    const cp1x = p1.x + (p2.x - p0.x) / 6;
    const cp1y = clamp(p1.y + (p2.y - p0.y) / 6, minY, maxY);
    const cp2x = p2.x - (p3.x - p1.x) / 6;
    const cp2y = clamp(p2.y - (p3.y - p1.y) / 6, minY, maxY);
    stroke += ` C ${cp1x.toFixed(1)} ${cp1y.toFixed(1)}, ${cp2x.toFixed(1)} ${cp2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
  }
  return { stroke, fill: `${stroke} L ${width} ${height} L 0 ${height} Z` };
}

const trendPaths = computed(() => generateTrend(rateHistory.value));
</script>

<style scoped>
.traffic-strip {
  min-width: 0;
  color: var(--text-primary);
  background: var(--surface-panel);
  font-family: var(--font-body);
}

.traffic-strip--card {
  padding: 10px 12px 7px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--ui-radius-lg);
}

.traffic-strip--detail {
  height: 100%;
  padding: 10px 12px;
}

.traffic-strip__header,
.traffic-strip__identity,
.traffic-strip__context,
.traffic-strip__cycle-total,
.traffic-strip__row {
  display: flex;
  align-items: center;
}

.traffic-strip__header {
  justify-content: space-between;
  gap: 10px;
  min-width: 0;
}

.traffic-strip__identity {
  gap: 6px;
  min-width: 0;
}

.traffic-strip__identity strong {
  flex: 0 0 auto;
  color: var(--text-secondary);
  font-size: var(--text-md);
  font-weight: 700;
}

.traffic-strip__interface {
  overflow: hidden;
  max-width: 88px;
  color: var(--text-muted);
  font-size: var(--text-2xs);
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.traffic-strip__activity {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-muted);
}

.traffic-strip__activity.is-low { background: var(--accent-cyan); }
.traffic-strip__activity.is-active { background: var(--warning); }
.traffic-strip__activity.is-busy { background: var(--danger); }

.traffic-strip__context {
  justify-content: flex-end;
  gap: 8px;
  min-width: 0;
}

.traffic-strip__cycle-total {
  flex: 0 0 auto;
  gap: 3px;
  min-height: 20px;
  padding: 1px 6px;
  border: 1px solid color-mix(in srgb, var(--accent-blue) 20%, var(--border-subtle));
  border-radius: var(--ui-radius-sm);
  color: var(--accent-blue);
  background: color-mix(in srgb, var(--accent-blue) 7%, transparent);
  font-variant-numeric: tabular-nums;
}

.traffic-strip__cycle-total > span,
.traffic-strip__cycle-total > small {
  color: color-mix(in srgb, var(--accent-blue) 72%, var(--text-muted));
  font-size: var(--text-2xs);
  font-weight: 700;
}

.traffic-strip__cycle-total > strong {
  font-size: var(--text-lg);
  font-weight: 800;
  line-height: 1;
}

.traffic-strip__values {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  margin-top: 8px;
}

.traffic-strip__segment {
  display: grid;
  grid-template-columns: minmax(28px, 34px) minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 0 10px;
  border-left: 1px solid var(--border-subtle);
}

.traffic-strip__segment:first-child {
  padding-left: 0;
  border-left: 0;
}

.traffic-strip__segment:last-child {
  padding-right: 0;
}

.traffic-strip--detail .traffic-strip__segment {
  grid-template-columns: 30px minmax(0, 1fr);
  gap: 3px;
  padding-inline: 4px;
}

.traffic-strip--detail .traffic-strip__segment:first-child {
  padding-left: 0;
}

.traffic-strip--detail .traffic-strip__segment:last-child {
  padding-right: 0;
}

.traffic-strip--detail .traffic-strip__row {
  grid-template-columns: 10px minmax(0, 1fr) max-content;
  gap: 2px;
}

.traffic-strip--detail .traffic-strip__row strong {
  font-size: var(--text-base);
}

.traffic-strip--detail .traffic-strip__row small {
  font-size: var(--text-2xs);
}

.traffic-strip__segment-title {
  display: grid;
  align-content: center;
  gap: 2px;
  min-width: 0;
  color: var(--text-muted);
  font-size: var(--text-xs);
  font-weight: 700;
  line-height: 1.2;
}

.traffic-strip__segment-title > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.traffic-strip__rows {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.traffic-strip__row {
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) max-content;
  align-items: baseline;
  gap: 4px;
  min-width: 0;
  font-family: var(--font-body);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.traffic-strip__row strong {
  overflow: hidden;
  color: var(--text-primary);
  font-size: var(--text-lg);
  font-weight: 800;
  text-align: right;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.traffic-strip__row small {
  color: var(--text-muted);
  font-size: var(--text-xs);
  white-space: nowrap;
}

.traffic-strip__arrow {
  font-family: var(--font-body);
  font-weight: 800;
  text-align: center;
}

.traffic-strip__arrow.is-down {
  color: var(--accent-cyan);
}

.traffic-strip__arrow.is-up {
  color: var(--accent-blue);
}

.traffic-strip__trend {
  display: block;
  margin-top: 5px;
  opacity: 0.82;
}

@media (max-width: 520px) {
  .traffic-strip__segment {
    padding-inline: 7px;
    gap: 5px;
  }

  .traffic-strip__row {
    grid-template-columns: 10px minmax(0, 1fr) max-content;
  }

}
</style>
