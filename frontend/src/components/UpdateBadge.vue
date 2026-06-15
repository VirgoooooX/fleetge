<template>
  <span class="update-badge" :class="`is-${statusClass}`" :title="hint">
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  status: string;
}>();

const label = computed(() => {
  const labels: Record<string, string> = {
    up_to_date: "最新",
    updatable: "Update",
    needs_auth: "需认证",
    check_failed: "检查失败",
  };
  return labels[props.status] || props.status;
});

const statusClass = computed(() => {
  const classes: Record<string, string> = {
    up_to_date: "fresh",
    updatable: "update",
    needs_auth: "warning",
    check_failed: "muted",
  };
  return classes[props.status] || "muted";
});

const hint = computed(() => {
  const hints: Record<string, string> = {
    up_to_date: "镜像已是最新",
    updatable: "远端镜像 digest 不同，可更新",
    needs_auth: "Registry 返回认证/授权要求，无法判断是否有更新",
    check_failed: "镜像检查失败，无法判断是否有更新",
  };
  return hints[props.status] || props.status;
});
</script>

<style scoped>
.update-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 18px;
  padding: 0 7px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 800;
  line-height: 18px;
  white-space: nowrap;
}

.is-update {
  border-color: rgba(248, 113, 113, 0.28);
  background: rgba(248, 113, 113, 0.10);
  color: #f87171;
}

.is-warning {
  border-color: rgba(245, 158, 11, 0.28);
  background: rgba(245, 158, 11, 0.10);
  color: var(--warning);
}

.is-fresh {
  border-color: rgba(34, 197, 94, 0.22);
  background: rgba(34, 197, 94, 0.08);
  color: var(--success);
}

.is-muted {
  border-color: var(--border-subtle);
  background: rgba(148, 163, 184, 0.10);
  color: var(--text-secondary);
}
</style>
