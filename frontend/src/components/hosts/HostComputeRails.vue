<template>
  <section class="compute-rail-group">
    <div v-for="rail in rails" :key="rail.label" class="compute-rail-item">
      <div class="rail-top">
        <span class="rail-label">{{ t(rail.label) }}</span>
        <strong class="rail-val u-mono u-tabular" :style="{ color: rail.color }">
          {{ rail.display }}%
        </strong>
      </div>
      <div class="rail-track">
        <div class="rail-fill" :style="{ width: `${rail.percent}%`, background: rail.color }" />
      </div>
      <div class="rail-sub u-mono u-tabular" :title="rail.detail">{{ rail.detail }}</div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";
import type { HostSummary } from "@/stores/dashboard";
import { formatBytes } from "@/utils/formatBytes";

const props = defineProps<{ metrics: NonNullable<HostSummary["metrics"]> }>();
const { t } = useI18n();

function percentUsed(used: number, total: number): number {
  return total > 0 ? Math.min(100, Math.max(0, Math.round(100 * used / total))) : 0;
}

function metricColor(percent: number, dangerThreshold = 90): string {
  if (percent >= dangerThreshold) return "var(--danger)";
  if (percent >= 80) return "var(--warning)";
  return "var(--accent-blue)";
}

const rails = computed(() => {
  const metrics = props.metrics;
  const cpu = Math.min(100, Math.max(0, metrics.cpuPercent));
  const memory = percentUsed(metrics.memoryUsed, metrics.memoryTotal);
  const disk = percentUsed(metrics.diskUsed, metrics.diskTotal);
  const load = metrics.loadavg?.[0];
  return [
    {
      label: "hostCard.cpu",
      percent: cpu,
      display: cpu.toFixed(1),
      color: metricColor(cpu, 95),
      detail: load == null ? "—" : t("hostCard.loadAverage", { load: load.toFixed(2) }),
    },
    {
      label: "hostCard.memory",
      percent: memory,
      display: memory,
      color: metricColor(memory),
      detail: `${formatBytes(metrics.memoryUsed)} / ${formatBytes(metrics.memoryTotal)}`,
    },
    {
      label: "hostCard.disk",
      percent: disk,
      display: disk,
      color: metricColor(disk),
      detail: `${formatBytes(metrics.diskUsed)} / ${formatBytes(metrics.diskTotal)}`,
    },
  ];
});
</script>

<style scoped>
/* 算力三联微轨 */
.compute-rail-group {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 12px;
}

.compute-rail-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.rail-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
}

.rail-label {
  color: var(--text-secondary, #94a3b8);
  font-weight: 600;
}

.rail-val {
  font-size: 14px;
  font-weight: 700;
}

.rail-track {
  width: 100%;
  height: 4px;
  background: rgba(148, 163, 184, 0.14);
  border-radius: 99px;
  overflow: hidden;
}

.rail-fill {
  height: 100%;
  border-radius: inherit;
  transition: width 0.3s ease;
}

.rail-sub {
  font-size: 12px;
  color: var(--text-muted, #64748b);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
