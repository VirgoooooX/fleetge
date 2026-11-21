<template>
  <aside id="ops-sidebar" tabindex="-1" class="ops-sidebar" :class="{ 'is-mobile-open': open }" :inert="mobile && !open">
    <button v-if="mobile && open" type="button" class="ops-sidebar-close" :aria-label="t('mobile.closeMenu')" @click="emit('close')">
      <el-icon><X /></el-icon>
    </button>
    <button type="button" class="ops-brand" @click="router.push('/')">
      <div class="ops-brand-mark">
        <AppLogo />
      </div>
      <div class="ops-brand-title">{{ t('brand.name') }}</div>
    </button>

    <nav class="ops-nav" :aria-label="t('nav.hostsSection')">
      <button
        v-for="item in navItems"
        :key="item.id"
        class="ops-nav-item"
        :class="{ active: isActive(item.path) }"
        :aria-current="isActive(item.path) ? 'page' : undefined"
        type="button"
        @click="router.push(item.path)"
      >
        <el-icon><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </button>

      <!-- 主机管理一级标题与二级列表组 -->
      <div class="ops-nav-group">
        <div class="ops-nav-header">
          <button
            class="ops-nav-item"
            :class="{ active: onHostsSettings }"
            :aria-current="onHostsSettings ? 'page' : undefined"
            type="button"
            @click="router.push({ name: 'settings', query: { section: 'hosts' } })"
          >
            <el-icon><Server /></el-icon>
            <span>{{ t('nav.hosts') }}</span>
          </button>
          <button
            class="ops-nav-add-btn"
            type="button"
            :title="t('settings.hosts.add')"
            :aria-label="t('settings.hosts.add')"
            @click.stop="router.push({ name: 'settings', query: { section: 'hosts', action: 'add-host' } })"
          >
            <el-icon><Plus /></el-icon>
          </button>
        </div>

        <!-- 二级子列表 -->
        <div class="ops-nav-submenu">
          <button
            v-for="host in store.hosts"
            :key="host.host_id"
            class="ops-host-link"
            :class="{ active: route.params.hostId === host.host_id }"
            :aria-current="route.params.hostId === host.host_id ? 'page' : undefined"
            type="button"
            @click="router.push({ name: 'host-detail', params: { hostId: host.host_id } })"
          >
            <StatusIcon :status="host.status" />
            <span class="ops-host-name">{{ host.display_name }}</span>
            <span v-if="store.getHostUpdateCount(host.host_id) > 0" class="ops-host-update">
              {{ store.getHostUpdateCount(host.host_id) }}
            </span>
          </button>
        </div>
      </div>
    </nav>

    <div class="ops-sidebar-footer">
      <button class="ops-sidebar-footer-btn ops-sidebar-mobile-action" type="button" @click="emit('switch-locale')">
        <el-icon><Globe /></el-icon>
        <span>{{ localeLabel === '中' ? '简体中文' : 'English' }}</span>
      </button>
      <ThemeToggle mobile :disabled="!open" />
      <button class="ops-sidebar-footer-btn ops-sidebar-mobile-action" type="button" :disabled="store.manualLoading" @click="store.refreshAll">
        <el-icon><RefreshCw /></el-icon>
        <span>{{ t('shell.refresh') }}</span>
      </button>
      <button class="ops-sidebar-footer-btn ops-sidebar-mobile-action logout" type="button" @click="emit('logout')">
        <el-icon><LogOut /></el-icon>
        <span>{{ t('shell.logout') }}</span>
      </button>
    </div>

    <!-- Resize Handle -->
    <div
      class="ops-sidebar-resizer"
      :class="{ 'is-dragging': isDragging }"
      role="separator"
      tabindex="0"
      aria-orientation="vertical"
      aria-controls="ops-sidebar"
      :aria-label="t('nav.hostsSection')"
      :aria-valuenow="width"
      :aria-valuemin="MIN_WIDTH"
      :aria-valuemax="MAX_WIDTH"
      @pointerdown="startResize"
      @pointermove="resize"
      @lostpointercapture="finishResize"
      @keydown="resizeByKey"
    />
  </aside>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useI18n } from "vue-i18n";
import { useRoute, useRouter } from "vue-router";
import { Globe, Grid, Home, LogOut, Map as MapIcon, Plus, RefreshCw, Server, X } from "@lucide/vue";
import { useDashboardStore } from "@/stores/dashboard";
import AppLogo from "@/components/AppLogo.vue";
import StatusIcon from "@/components/StatusIcon.vue";
import ThemeToggle from "./ThemeToggle.vue";

const props = defineProps<{ open: boolean; mobile: boolean; localeLabel: string }>();
const emit = defineEmits<{ "switch-locale": []; logout: []; close: []; "resize-end": [width: number] }>();
const width = defineModel<number>("width", { required: true });
const { t } = useI18n();
const route = useRoute();
const router = useRouter();
const store = useDashboardStore();
const isDragging = ref(false);
const MIN_WIDTH = 180;
const MAX_WIDTH = 450;
const onHostsSettings = computed(() => route.name === "settings" && route.query.section === "hosts");
const navItems = computed(() => [
  { id: "dashboard", label: t("nav.dashboard"), path: "/", icon: Home },
  { id: "fleet-map", label: t("nav.map"), path: "/map", icon: MapIcon },
  { id: "apps", label: t("nav.apps"), path: "/apps", icon: Grid },
]);

function isActive(path: string) {
  return path === "/" ? route.name === "dashboard" : route.path.startsWith(path);
}

function setWidth(value: number) {
  const next = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, value));
  width.value = next;
  return next;
}

let pointer: { id: number; element: HTMLElement; startX: number; startWidth: number; currentWidth: number } | null = null;
function startResize(event: PointerEvent) {
  if (!event.isPrimary || event.button !== 0) return;
  const element = event.currentTarget as HTMLElement;
  element.setPointerCapture(event.pointerId);
  pointer = { id: event.pointerId, element, startX: event.clientX, startWidth: width.value, currentWidth: width.value };
  isDragging.value = true;
  document.body.classList.add("is-resizing-sidebar");
}

function resize(event: PointerEvent) {
  if (pointer?.id === event.pointerId) {
    pointer.currentWidth = setWidth(pointer.startWidth + event.clientX - pointer.startX);
  }
}

function finishResize() {
  if (!pointer) return;
  const { id, element, currentWidth } = pointer;
  pointer = null;
  if (element.hasPointerCapture(id)) element.releasePointerCapture(id);
  isDragging.value = false;
  document.body.classList.remove("is-resizing-sidebar");
  emit("resize-end", currentWidth);
}

function resizeByKey(event: KeyboardEvent) {
  const step = event.shiftKey ? 30 : 10;
  let nextWidth: number;
  if (event.key === "ArrowLeft") nextWidth = width.value - step;
  else if (event.key === "ArrowRight") nextWidth = width.value + step;
  else if (event.key === "Home") nextWidth = MIN_WIDTH;
  else if (event.key === "End") nextWidth = MAX_WIDTH;
  else return;
  event.preventDefault();
  emit("resize-end", setWidth(nextWidth));
}

watch(() => props.mobile, finishResize);
onBeforeUnmount(finishResize);
</script>

<style scoped>
.ops-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: 12px;
  border-right: 1px solid var(--border-subtle);
  background: var(--sidebar-bg), var(--surface-panel-raised);
}

.ops-sidebar-close {
  align-self: flex-end;
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--ui-radius-md);
  background: var(--surface-panel);
  color: inherit;
  cursor: pointer;
}

.ops-brand {
  width: 100%;
  border: 0;
  border-bottom: 1px solid var(--border-subtle);
  background: transparent;
  color: inherit;
  font: inherit;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 0 8px 15px;
  cursor: pointer;
}

.ops-brand-mark {
  width: 76px;
  height: 76px;
  flex: 0 0 76px;
  display: grid;
  place-items: center;
  margin: 0;
}

.ops-brand-title {
  font-size: 30px;
  line-height: 1;
  font-weight: 700;
  margin: 0;
}

.ops-nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.ops-nav-item,
.ops-host-link {
  width: 100%;
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  padding: 0 10px;
  text-align: left;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
}

.ops-nav-item .el-icon {
  width: 22px;
  height: 22px;
  margin-left: -2px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: var(--text-muted);
}

.ops-nav-item:hover,
.ops-host-link:hover {
  border-color: var(--border-strong);
  background: var(--nav-hover-bg);
  color: var(--text-primary);
}

.ops-nav-item.active,
.ops-host-link.active {
  border-color: var(--nav-active-border);
  background: var(--nav-active-bg);
  color: var(--text-primary);
  box-shadow: var(--nav-active-shadow);
}

.ops-nav-item.active .el-icon {
  background: var(--nav-icon-active-bg);
  color: var(--accent-blue);
}

.ops-host-update {
  margin-left: auto;
  min-width: 22px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(248, 113, 113, 0.14);
  color: var(--danger);
  font-size: 11px;
  font-weight: 700;
}

.ops-nav-group {
  display: flex;
  flex-direction: column;
}

.ops-nav-header {
  position: relative;
}

.ops-nav-header .ops-nav-item {
  padding-right: 38px;
}

.ops-nav-add-btn {
  position: absolute;
  right: 6px;
  top: 50%;
  transform: translateY(-50%);
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  padding: 0;
  transition:
    border-color var(--duration-normal, 180ms) ease,
    background-color var(--duration-normal, 180ms) ease,
    color var(--duration-normal, 180ms) ease;
  z-index: 2;
}

.ops-nav-add-btn:hover {
  border-color: var(--border-strong);
  background: var(--surface-panel);
  color: var(--text-primary);
}

.ops-nav-submenu {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 4px;
  padding-left: 20px;
}

.ops-host-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ops-sidebar-footer {
  display: none;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
  flex-direction: column;
  gap: 8px;
}

.ops-sidebar-footer :deep(.ops-sidebar-footer-btn) {
  width: 100%;
  min-height: 38px;
  display: flex;
  align-items: center;
  gap: 9px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font: inherit;
  padding: 0 10px;
  text-align: left;
  transition: background 160ms ease, border-color 160ms ease, color 160ms ease;
}

.ops-sidebar-footer :deep(.ops-sidebar-footer-btn):hover {
  border-color: var(--border-strong);
  background: var(--nav-hover-bg);
  color: var(--text-primary);
}

.ops-sidebar-footer :deep(.ops-sidebar-footer-btn).active {
  border-color: var(--nav-active-border);
  background: var(--nav-active-bg);
  color: var(--text-primary);
  box-shadow: var(--nav-active-shadow);
}

.ops-sidebar-mobile-action {
  display: none;
}

.ops-sidebar-footer :deep(.ops-sidebar-footer-btn) .el-icon {
  width: 22px;
  height: 22px;
  margin-left: -2px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: var(--text-muted);
}

.ops-sidebar-footer :deep(.ops-sidebar-footer-btn).logout:hover {
  border-color: rgba(248, 113, 113, 0.35);
  background: rgba(248, 113, 113, 0.08);
  color: var(--danger);
}

.ops-sidebar-footer :deep(.ops-sidebar-footer-btn).logout:hover .el-icon {
  color: var(--danger);
}


.ops-sidebar-resizer {
  position: absolute;
  top: 0;
  bottom: 0;
  right: -3px;
  width: 6px;
  cursor: col-resize;
  z-index: 50;
}

.ops-sidebar-resizer::after {
  content: "";
  position: absolute;
  top: 0;
  bottom: 0;
  left: 2px;
  width: 2px;
  background: transparent;
  transition: background-color 0.15s ease, box-shadow 0.15s ease;
}

.ops-sidebar-resizer:hover::after,
.ops-sidebar-resizer.is-dragging::after {
  background: var(--accent-blue);
  box-shadow: 0 0 8px var(--accent-blue);
}

:global(body.is-resizing-sidebar) {
  user-select: none !important;
  cursor: col-resize !important;
}

:global(body.is-resizing-sidebar *) {
  user-select: none !important;
  cursor: col-resize !important;
}

.ops-sidebar-resizer {
  touch-action: none;
}

.ops-sidebar-resizer:focus-visible::after {
  background: var(--accent-blue);
}

@media (max-width: 900px) {
  /* Sidebar → fixed overlay drawer */
  .ops-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    height: 100vh;
    height: 100dvh;
    width: 280px;
    z-index: 100;
    padding: 12px;
    padding-top: calc(12px + env(safe-area-inset-top, 0px));
    padding-bottom: calc(12px + env(safe-area-inset-bottom, 0px));
    border-right: 1px solid var(--border-subtle);
    transform: translateX(-100%);
    transition: transform 0.3s ease;
    overflow-y: auto;
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
  }

  .ops-sidebar.is-mobile-open {
    transform: translateX(0);
    box-shadow: 6px 0 30px rgba(0, 0, 0, 0.5);
  }

  .ops-sidebar-footer {
    display: flex;
  }

  .ops-sidebar-footer :deep(.ops-sidebar-mobile-action) {
    display: flex;
  }

  .ops-sidebar-resizer {
    display: none !important;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ops-sidebar,
  .ops-nav-item,
  .ops-host-link,
  .ops-nav-add-btn,
  .ops-sidebar-resizer::after,
  .ops-sidebar-footer :deep(.ops-sidebar-footer-btn) {
    transition: none;
  }
}
</style>
