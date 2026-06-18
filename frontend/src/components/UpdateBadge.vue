<template>
  <span class="update-badge" :class="`is-${statusClass}`" :title="hint">
    {{ label }}
  </span>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useI18n } from "vue-i18n";

const props = defineProps<{
  status: string;
}>();

const { t } = useI18n();

const label = computed(() => {
  const keys: Record<string, string> = {
    up_to_date: "update.status.upToDate",
    updatable: "update.status.updatable",
    needs_auth: "update.status.needsAuth",
    check_failed: "update.status.checkFailed",
  };
  const key = keys[props.status];
  return key ? t(key as any) : props.status;
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
  const keys: Record<string, string> = {
    up_to_date: "update.hint.upToDate",
    updatable: "update.hint.updatable",
    needs_auth: "update.hint.needsAuth",
    check_failed: "update.hint.checkFailed",
  };
  const key = keys[props.status];
  return key ? t(key as any) : props.status;
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
  font-weight: 750;
  line-height: 18px;
  white-space: nowrap;
}

.is-update {
  border-color: rgba(248, 113, 113, 0.28);
  background: rgba(248, 113, 113, 0.10);
  color: #f87171;
}

[data-theme="light"] .is-update {
  color: var(--danger);
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
