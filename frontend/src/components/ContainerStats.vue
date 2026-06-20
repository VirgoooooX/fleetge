<template>
  <div class="container-stats">
    <div class="stat-row">
      <el-tooltip :content="t('containerStats.cpuUsage')" placement="top">
        <span class="stat-item">CPU {{ stats.cpu_percent.toFixed(1) }}%</span>
      </el-tooltip>
      <el-tooltip :content="t('containerStats.memUsage')" placement="top">
        <span class="stat-item">MEM {{ formatBytes(stats.memory_usage) }}</span>
      </el-tooltip>
    </div>
    <div class="stat-row">
      <el-tooltip :content="t('containerStats.networkIO')" placement="top">
        <span class="stat-item">↓{{ formatBytes(stats.network_rx_bytes) }} ↑{{ formatBytes(stats.network_tx_bytes) }}</span>
      </el-tooltip>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useI18n } from "vue-i18n";
import type { ContainerStatsData } from "./ContainerTable.vue";

defineProps<{
  stats: ContainerStatsData;
}>();

const { t } = useI18n();

function formatBytes(bytes: number): string {
  if (!bytes) return "0";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }
  return `${size.toFixed(1)}${units[i]}`;
}
</script>

<style scoped>
.container-stats {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.stat-row {
  display: flex;
  gap: 8px;
}
.stat-item {
  font-family: var(--font-body);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  white-space: nowrap;
}
</style>
