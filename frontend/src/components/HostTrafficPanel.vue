<template>
  <section class="traffic-panel">
    <div class="traffic-heading">
      <div>
        <span>{{ t("traffic.kicker") }}</span>
        <strong>{{ t("traffic.title") }}</strong>
      </div>
      <div class="traffic-tabs">
        <button :class="{ active: range === 'today' }" type="button" @click="setRange('today')">{{ t("traffic.today") }}</button>
        <button :class="{ active: range === 'month' }" type="button" @click="setRange('month')">{{ t("traffic.month") }}</button>
        <button type="button" :disabled="loading" @click="load(true)">{{ t("traffic.sync") }}</button>
      </div>
    </div>
    <div class="traffic-values">
      <article><span>{{ t("traffic.download") }}</span><strong>{{ historyValue(report?.rxBytes) }}</strong></article>
      <article><span>{{ t("traffic.upload") }}</span><strong>{{ historyValue(report?.txBytes) }}</strong></article>
      <article><span>{{ t("traffic.total") }}</span><strong>{{ historyValue(report?.totalBytes) }}</strong></article>
      <article><span>{{ t("traffic.live") }}</span><strong>↓ {{ formatRate(metrics?.networkRxRate) }} · ↑ {{ formatRate(metrics?.networkTxRate) }}</strong></article>
    </div>
    <div class="traffic-meta">
      <span :class="['traffic-scope', metrics?.networkScope || 'unknown']">{{ scopeLabel }}</span>
      <span>{{ (metrics?.networkInterfaces || []).join(", ") || t("traffic.noInterface") }}</span>
      <span>{{ metrics?.collectorState || "—" }}</span>
      <span v-if="report?.hasGap || metrics?.hasGap" class="traffic-gap">{{ t("traffic.hasGap") }}</span>
      <span v-if="!hasHistory && !loading">{{ t("traffic.noHistory") }}</span>
      <span v-if="loading">{{ t("traffic.loading") }}</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { apiClient } from "@/api/client";
import type { HostSummary } from "@/stores/dashboard";

const props = defineProps<{ hostId: string; metrics?: HostSummary["metrics"] }>();
const { t } = useI18n();
const range = ref<"today" | "month">("today");
const report = ref<any>(null);
const loading = ref(false);
const hasHistory = computed(() => Boolean(
  report.value?.buckets?.length || report.value?.daily?.length || report.value?.openBucket,
));
const scopeLabel = computed(() => {
  if (props.metrics?.networkScope === "host_wan") return t("traffic.hostWan");
  if (props.metrics?.networkScope === "container") return t("traffic.containerOnly");
  return t("traffic.unknownScope");
});

function formatBytes(value: number | null | undefined) {
  if (value == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  let size = Math.max(0, value);
  let index = 0;
  while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
  return `${size.toFixed(index === 0 ? 0 : 2)} ${units[index]}`;
}

function formatRate(value: number | null | undefined) {
  if (value == null) return "—";
  return `${formatBytes(value)}/s`;
}

function historyValue(value: number | null | undefined) {
  return hasHistory.value ? formatBytes(value) : "—";
}

async function load(sync = true) {
  if (loading.value) return;
  loading.value = true;
  try {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const response = await apiClient.get(`/api/hosts/${encodeURIComponent(props.hostId)}/traffic`, {
      params: { range: range.value, timezone, sync },
    });
    report.value = response.data;
  } finally {
    loading.value = false;
  }
}

function setRange(next: "today" | "month") {
  if (range.value === next) return;
  range.value = next;
  void load(false);
}

onMounted(() => void load(true));
watch(() => props.hostId, () => void load(true));
</script>

<style scoped>
.traffic-panel{display:grid;grid-template-columns:minmax(180px,.8fr) minmax(0,2.4fr);gap:12px;padding:12px 14px;border:1px solid var(--border-subtle);border-radius:8px;background:var(--surface-panel)}
.traffic-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.traffic-heading>div:first-child{display:grid;gap:3px}.traffic-heading span{color:var(--text-muted);font-size:var(--text-2xs);letter-spacing:.08em}.traffic-heading strong{font-size:var(--text-sm)}
.traffic-tabs{display:flex;gap:4px}.traffic-tabs button{padding:5px 8px;border:1px solid var(--border-subtle);border-radius:5px;color:var(--text-secondary);background:var(--surface-panel-raised);cursor:pointer}.traffic-tabs button.active{color:var(--accent-cyan);border-color:color-mix(in srgb,var(--accent-cyan) 35%,var(--border-subtle))}.traffic-tabs button:disabled{opacity:.5}
.traffic-values{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.traffic-values article{display:grid;gap:4px;padding:7px 9px;border-left:1px solid var(--border-subtle)}.traffic-values span{color:var(--text-muted);font-size:var(--text-2xs)}.traffic-values strong{font:700 var(--text-xs) var(--font-mono);white-space:nowrap}
.traffic-meta{grid-column:1/-1;display:flex;gap:12px;flex-wrap:wrap;color:var(--text-muted);font-size:var(--text-2xs)}.traffic-scope{padding:2px 6px;border-radius:99px;background:var(--surface-panel-raised)}.traffic-scope.host_wan{color:var(--accent-cyan)}.traffic-scope.container,.traffic-gap{color:var(--warning)}
@media(max-width:900px){.traffic-panel{grid-template-columns:1fr}.traffic-values{grid-template-columns:repeat(2,1fr)}.traffic-meta{grid-column:1}}
</style>
