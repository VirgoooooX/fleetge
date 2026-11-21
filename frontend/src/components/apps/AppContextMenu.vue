<template>
  <Teleport to="body">
    <div
      ref="menu"
      class="custom-context-menu"
      role="menu"
      :aria-label="app.title || app.stack_name"
      :style="{ top: y + 'px', left: x + 'px' }"
      @keydown="handleKeydown"
    >
      <template v-for="item in items" :key="item.action">
        <el-divider v-if="item.action === 'edit-profile'" class="menu-divider" role="separator" />
        <button type="button" role="menuitem" tabindex="-1" class="context-item" :aria-disabled="item.disabled || undefined" @click="select(item)">
          <el-icon aria-hidden="true"><component :is="item.icon" /></el-icon>
          <span>{{ t(item.label) }}</span>
        </button>
      </template>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { Copy, Monitor, Pause, Play, RefreshCw, Settings } from "@lucide/vue";
import { isRunning, type LauncherApp } from "@/api/apps";
import type { AppMenuAnchor } from "./AppTile.vue";

export type AppCommand = "open-dashboard" | "restart" | "stop" | "start" | "copy-url" | "edit-profile";

const props = defineProps<{ app: LauncherApp; anchor: AppMenuAnchor }>();
const emit = defineEmits<{ command: [command: AppCommand]; close: [] }>();
const { t } = useI18n();
const menu = ref<HTMLElement | null>(null);
const x = ref(props.anchor.x);
const y = ref(props.anchor.y);
const items = computed(() => {
  const locked = props.app.management_status === "unmanaged";
  const running = isRunning(props.app.status);
  return [
    { action: "open-dashboard", icon: Monitor, label: "apps.menu.openDashboard", disabled: false },
    { action: "restart", icon: RefreshCw, label: "apps.menu.restartApp", disabled: locked },
    { action: running ? "stop" : "start", icon: running ? Pause : Play, label: running ? "apps.menu.stopApp" : "apps.menu.startApp", disabled: locked },
    { action: "copy-url", icon: Copy, label: "apps.menu.copyUrl", disabled: !props.app.app_url },
    { action: "edit-profile", icon: Settings, label: "apps.menu.editProfile", disabled: false },
  ] as const;
});

function buttons() {
  return Array.from(menu.value?.querySelectorAll<HTMLButtonElement>("[role=menuitem]") ?? []);
}

async function placeMenu() {
  const anchor = props.anchor;
  await nextTick();
  if (!menu.value || anchor !== props.anchor) return;
  const { width, height } = menu.value.getBoundingClientRect();
  const margin = 8;
  const maxX = document.documentElement.clientWidth - width - margin;
  const maxY = document.documentElement.clientHeight - height - margin;
  x.value = Math.max(margin, Math.min(anchor.x > maxX ? anchor.x - width : anchor.x, maxX));
  y.value = Math.max(margin, Math.min(anchor.y > maxY ? anchor.y - height : anchor.y, maxY));
  buttons()[0]?.focus({ preventScroll: true });
}

function dismiss(restoreFocus = false) {
  if (restoreFocus) props.anchor.element.focus({ preventScroll: true });
  emit("close");
}

function select(item: (typeof items.value)[number]) {
  if (item.disabled) return;
  dismiss(true);
  emit("command", item.action);
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === "Escape" || event.key === "Tab") {
    if (event.key === "Escape") event.preventDefault();
    dismiss(true);
    return;
  }
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const options = buttons();
  const current = options.indexOf(document.activeElement as HTMLButtonElement);
  const end = options.length - 1;
  const next = event.key === "Home" ? 0 : event.key === "End" ? end
    : event.key === "ArrowDown" ? (current + 1) % options.length
      : (current <= 0 ? end : current - 1);
  options[next]?.focus();
}

function closeOnOutsidePointer(event: PointerEvent) {
  if (event.target instanceof Node && !menu.value?.contains(event.target) && !props.anchor.element.contains(event.target)) dismiss();
}

watch(() => props.anchor, placeMenu);
onMounted(() => {
  void placeMenu();
  document.addEventListener("pointerdown", closeOnOutsidePointer);
});
onBeforeUnmount(() => document.removeEventListener("pointerdown", closeOnOutsidePointer));
</script>

<style scoped>
.custom-context-menu {
  position: fixed;
  box-sizing: border-box;
  max-width: calc(100vw - 16px);
  max-height: calc(100dvh - 16px);
  overflow: auto;
  z-index: 3000;
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  box-shadow: var(--ui-control-shadow);
  padding: 4px;
  min-width: 160px;
}

.context-item {
  width: 100%;
  border: 0;
  background: transparent;
  font: inherit;
  text-align: left;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  transition: background-color var(--duration-fast, 120ms) ease, color var(--duration-fast, 120ms) ease;
}

.context-item:hover,
.context-item:focus-visible {
  background: var(--ui-control-hover-bg);
  color: var(--text-primary);
}

.context-item[aria-disabled="true"] {
  opacity: 0.5;
  cursor: not-allowed;
}

.menu-divider {
  margin: 4px 0;
}

@media (prefers-reduced-motion: reduce) {
  .context-item {
    transition: none;
  }
}
</style>
