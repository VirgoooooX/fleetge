<template>
  <article class="app-tile" @contextmenu.prevent="openMenu($event, launcher)">
    <button ref="launcher" type="button" class="app-launch" @click="emit('launch')" @keydown.shift.f10.prevent="openMenu($event, launcher)" @keydown.context-menu.prevent="openMenu($event, launcher)">
      <span class="app-icon-wrap">
        <el-image v-if="app.icon_url" :src="getIconUrl(app.icon_url)" class="app-icon-img" fit="contain" aria-hidden="true">
          <template #error>
            <el-icon class="app-icon-fallback"><ImageIcon /></el-icon>
          </template>
        </el-image>
        <el-icon v-else class="app-icon-fallback" aria-hidden="true"><FolderOpen /></el-icon>
        <span v-if="app.update_status === 'updatable'" class="app-icon-update-dot" role="img" :aria-label="t('update.status.updatable')" :title="t('update.status.updatable')" />
      </span>
      <span class="app-info">
        <span class="app-title">{{ app.title || app.stack_name }}</span>
        <span class="app-meta">
          <span class="meta-pair meta-pair--host">
            <span class="host-connection-dot" :class="`host-${hostStatusType(app.host_status)}`" role="img" :aria-label="app.host_status" :title="app.host_status" />
            <span class="host-text">{{ app.host_name }}</span>
          </span>
          <span class="meta-spacer" aria-hidden="true" />
          <span class="meta-pair">
            <span class="dot-state" :class="`dot-${stackStatusType(app.status)}`" role="img" :aria-label="app.status" />
            <span class="count-text">{{ app.running_count }}/{{ app.service_count }}</span>
          </span>
        </span>
      </span>
    </button>
    <button
      type="button"
      class="app-menu-button"
      aria-haspopup="menu"
      :aria-label="t('stackGroup.moreActions') + ' · ' + (app.title || app.stack_name)"
      :aria-expanded="menuOpen"
      @click="openMenu($event, $event.currentTarget)"
    >
      <el-icon><MoreHorizontal /></el-icon>
    </button>
  </article>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useI18n } from "vue-i18n";
import { FolderOpen, Image as ImageIcon, MoreHorizontal } from "@lucide/vue";
import type { LauncherApp } from "@/api/apps";

export interface AppMenuAnchor {
  element: HTMLElement;
  x: number;
  y: number;
}

defineProps<{ app: LauncherApp; menuOpen: boolean }>();
const emit = defineEmits<{ launch: []; menu: [anchor: AppMenuAnchor] }>();
const { t } = useI18n();
const launcher = ref<HTMLButtonElement | null>(null);

function openMenu(event: Event, target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return;
  const bounds = target.getBoundingClientRect();
  const point = event instanceof MouseEvent && event.type === "contextmenu" && (event.clientX !== 0 || event.clientY !== 0);
  emit("menu", {
    element: target,
    x: point ? event.clientX : bounds.left,
    y: point ? event.clientY : bounds.bottom,
  });
}

function stackStatusType(status: string): string {
  if (status === "running" || status === "active") return "running";
  if (status === "exited") return "exited";
  if (status === "stopped" || status === "inactive") return "stopped";
  return "partial";
}

function hostStatusType(status: string): string {
  if (status === "online") return "online";
  if (status === "offline" || status === "unknown") return "offline";
  return "degraded";
}

function getIconUrl(value: string | null) {
  if (!value) return "";
  if (/^https?:\/\//.test(value)) return value;
  if (value.startsWith("/api/") || value.startsWith("/")) return value;
  return `/api/static/icons/${value}`;
}
</script>

<style scoped>
.app-tile {
  display: flex;
  position: relative;
  min-width: 0;
}

.app-launch {
  flex: 1;
  min-width: 0;
  font: inherit;
  text-align: left;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel);
  border-radius: var(--ui-radius-lg);
  padding: 8px 38px 8px 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  position: relative;
  transition: transform 0.22s cubic-bezier(0.16, 1, 0.3, 1), border-color 0.22s, background-color 0.22s, box-shadow 0.22s;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}

.app-launch:hover,
.app-tile:focus-within .app-launch {
  transform: translateY(-2px);
  border-color: var(--accent-blue);
  background: var(--ui-control-hover-bg);
  box-shadow: var(--ui-control-shadow);
}

.app-icon-wrap {
  position: relative;
  width: 56px;
  height: 56px;
  flex-shrink: 0;
  display: grid;
  place-items: center;
  overflow: visible;
}

.app-icon-img {
  width: 100%;
  height: 100%;
  border-radius: var(--ui-radius-md);
  object-fit: contain;
}

.app-icon-update-dot {
  position: absolute;
  top: -2px;
  right: -2px;
  width: 10px;
  height: 10px;
  background: var(--danger);
  border: 2px solid var(--surface-panel);
  border-radius: 50%;
  box-shadow: 0 0 6px var(--danger);
  z-index: 10;
}

.app-icon-fallback {
  font-size: 32px;
  color: var(--text-muted);
}

.app-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.app-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  line-height: 1.35;
  margin-bottom: 6px;
}

.app-meta {
  font-size: 12px;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 0;
  overflow: visible;
  min-width: 0;
}

.meta-pair {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  line-height: 16px;
  white-space: nowrap;
}

.meta-pair--host {
  overflow: hidden;
  flex: 0 1 auto;
  min-width: 0;
}

.meta-spacer {
  flex: 0 0 14px;
  width: 14px;
}

.host-text,
.count-text {
  line-height: 16px;
}

.host-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.host-connection-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
  flex: 0 0 8px;
}

.host-online {
  background: var(--success);
  box-shadow: 0 0 6px var(--success);
}

.host-degraded {
  background: var(--warning);
  box-shadow: 0 0 6px var(--warning);
}

.host-offline {
  background: var(--text-muted);
}

.dot-state {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex: 0 0 8px;
}

.dot-running {
  background: var(--success);
  box-shadow: 0 0 6px var(--success);
}

.dot-stopped {
  background: var(--text-muted);
}

.dot-exited {
  background: var(--danger);
  box-shadow: 0 0 6px var(--danger);
}

.dot-partial {
  background: var(--warning);
}

.app-menu-button {
  position: absolute;
  top: 50%;
  right: 6px;
  translate: 0 -50%;
  display: grid;
  place-items: center;
  width: 30px;
  height: 32px;
  padding: 0;
  border: 0;
  border-radius: var(--ui-radius-md);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
}

.app-menu-button:hover {
  background: var(--ui-control-hover-bg);
}

.app-launch:focus-visible,
.app-menu-button:focus-visible {
  outline: 2px solid var(--accent-blue);
  outline-offset: -2px;
}

@media (prefers-reduced-motion: reduce) {
  .app-launch {
    transition: none;
    transform: none;
  }
}
</style>
