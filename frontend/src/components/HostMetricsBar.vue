<template>
  <div class="metrics-bar-item">
    <span class="bar-label">{{ label }}</span>
    <el-progress
      :percentage="percent"
      :stroke-width="10"
      :show-text="false"
      :color="color"
    />
    <div class="bar-text">
      <span v-if="used != null && total != null" class="bar-value">
        {{ formatBytes(used) }} / {{ formatBytes(total) }} ({{ percent }}%)
      </span>
      <span v-else class="bar-value">{{ percent }}{{ unit }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  label: string;
  percent: number;
  unit?: string;
  used?: number;
  total?: number;
}>();

const color = computed(() => {
  const p = props.percent;
  if (p > 80) return "#f56c6c";
  if (p > 60) return "#e6a23c";
  return "#67c23a";
});

function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
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
.metrics-bar-item {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  padding: 12px;
  background: var(--surface-panel);
}
.bar-label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 600;
}
.bar-text {
  text-align: right;
}
.bar-value {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-secondary);
}
</style>
