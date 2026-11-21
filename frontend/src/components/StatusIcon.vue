<template>
  <span class="status-icon" :class="`status-${status}`">
    <el-tooltip :content="label" placement="top">
      <span class="status-dot" />
    </el-tooltip>
  </span>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{ status: string }>();
const { t } = useI18n();

const label = computed(() => {
  const keys: Record<string, string> = {
    online: "status.online",
    offline: "status.offline",
    degraded: "status.degraded",
    unknown: "status.unknown",
  };
  const key = keys[props.status];
  return key ? t(key as any) : props.status;
});
</script>

<style scoped>
.status-icon {
  display: inline-flex;
  align-items: center;
}
.status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.status-online .status-dot {
  background: var(--success);
  box-shadow: 0 0 6px var(--success);
}
.status-offline .status-dot {
  background: var(--danger);
}
.status-degraded .status-dot {
  background: var(--warning);
}
.status-unknown .status-dot {
  background: var(--text-muted);
}
</style>
