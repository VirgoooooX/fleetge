<template>
  <div class="ops-shell" :style="{ gridTemplateColumns: sidebarWidth + 'px minmax(0, 1fr)' }">
    <aside class="ops-sidebar" :class="{ 'is-mobile-open': sidebarOpen }">
      <div class="ops-brand" @click="router.push('/')">
        <div class="ops-brand-mark">
          <AppLogo />
        </div>
        <div class="ops-brand-title">{{ t('brand.name') }}</div>
      </div>

      <nav class="ops-nav" :aria-label="t('nav.hostsSection')">
        <button
          v-for="item in navItems"
          :key="item.id"
          class="ops-nav-item"
          :class="{ active: isActive(item.id, item.path) }"
          type="button"
          @click="router.push(item.path)"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
          <span
            v-if="item.badge != null && item.badge > 0"
            class="ops-nav-badge"
            :class="item.badgeTone"
          >
            {{ item.badge }}
          </span>
        </button>
      </nav>

      <div class="ops-host-list">
        <div class="ops-section-label">{{ t('nav.hostsSection') }}</div>
        <button
          v-for="host in store.hosts"
          :key="host.host_id"
          class="ops-host-link"
          :class="{ active: route.params.hostId === host.host_id }"
          type="button"
          @click="router.push(`/hosts/${host.host_id}`)"
        >
          <StatusIcon :status="host.status" />
          <span class="ops-host-name">{{ host.display_name }}</span>
          <span v-if="store.getHostUpdateCount(host.host_id) > 0" class="ops-host-update">
            {{ store.getHostUpdateCount(host.host_id) }}
          </span>
        </button>
      </div>

      <!-- Mobile sidebar footer actions -->
      <div class="ops-sidebar-footer">
        <button class="ops-sidebar-footer-btn" type="button" @click="switchLocale">
          <el-icon><Position /></el-icon>
          <span>{{ localeLabel === '中' ? '简体中文' : 'English' }}</span>
        </button>
        <button class="ops-sidebar-footer-btn" type="button" @click="theme.toggle()">
          <el-icon><component :is="themeIcon" /></el-icon>
          <span>{{ theme.current.value === 'dark' ? t('shell.switchLight') : t('shell.switchDark') }}</span>
        </button>
        <button class="ops-sidebar-footer-btn" type="button" :disabled="store.manualLoading" @click="store.refreshAll">
          <el-icon><Refresh /></el-icon>
          <span>{{ t('shell.refresh') }}</span>
        </button>
        <button class="ops-sidebar-footer-btn logout" type="button" @click="logout">
          <el-icon><SwitchButton /></el-icon>
          <span>{{ t('shell.logout') }}</span>
        </button>
      </div>

      <!-- Resize Handle -->
      <div
        class="ops-sidebar-resizer"
        :class="{ 'is-dragging': isDragging }"
        @mousedown="startResize"
      />
    </aside>

    <!-- Mobile backdrop overlay -->
    <div class="ops-mobile-backdrop" :class="{ 'is-visible': sidebarOpen }" @click="sidebarOpen = false" />

    <div class="ops-main">
      <header class="ops-topbar">
        <div class="ops-topbar-left">
          <button
            class="ops-mobile-menu-btn"
            :aria-label="sidebarOpen ? t('mobile.closeMenu') : t('mobile.openMenu')"
            @click="sidebarOpen = !sidebarOpen"
          >
            <el-icon :size="22">
              <Expand v-if="!sidebarOpen" />
              <Fold v-if="sidebarOpen" />
            </el-icon>
          </button>
          <div class="ops-topbar-kicker">{{ t('shell.kicker') }}</div>
          <div class="ops-topbar-title-row">
            <h1 class="ops-topbar-title">{{ pageTitle }}</h1>
            <div v-if="currentHost" class="ops-host-tags">
              <el-tag v-if="currentHost.os_info" size="small" type="info">
                {{ currentHost.os_info }}
              </el-tag>
              <el-tag v-if="currentHost.docker_version" size="small">
                Docker {{ currentHost.docker_version }}
              </el-tag>
              <el-tag v-if="currentHost.architecture" size="small" type="info">
                {{ currentHost.architecture }}
              </el-tag>
            </div>
          </div>
        </div>
        <div class="ops-topbar-right">
          <div class="ops-control ops-status-pill">
            <span class="ops-health-dot" />
            {{ t('shell.onlineCount', { online: store.onlineCount, total: store.hosts.length }) }}
          </div>
          <div class="ops-control ops-status-pill warning" v-if="store.updateCount > 0">
            {{ t('shell.updateCount', { count: store.updateCount }) }}
          </div>
          <el-button
            class="ops-control ui-icon-button"
            size="small"
            aria-label="EN/中"
            @click="switchLocale"
          >
            {{ localeLabel }}
          </el-button>
          <el-button
            class="ops-control ui-icon-button"
            size="small"
            :icon="themeIcon"
            :aria-label="theme.current.value === 'dark' ? t('shell.switchLight') : t('shell.switchDark')"
            @click="theme.toggle()"
          />
          <el-button
            class="ops-control ui-button ui-button--compact"
            size="small"
            :loading="store.manualLoading"
            @click="store.refreshAll"
          >
            <el-icon><Refresh /></el-icon>
            {{ t('shell.refresh') }}
          </el-button>
          <el-button class="ops-control ui-button ui-button--compact ui-button--muted" size="small" @click="logout">
            <el-icon><SwitchButton /></el-icon>
            {{ t('shell.logout') }}
          </el-button>
        </div>
      </header>

      <main class="ops-content" :class="{ 'is-host-detail': route.name === 'host-detail' }">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import {
  Collection,
  Expand,
  Fold,
  House,
  List,
  Moon,
  Refresh,
  Sunny,
  SwitchButton,
  Warning,
  Setting,
  Position,
} from "@element-plus/icons-vue";
import AppLogo from "@/components/AppLogo.vue";
import StatusIcon from "@/components/StatusIcon.vue";
import { useAuthStore } from "@/stores/auth";
import { useDashboardStore } from "@/stores/dashboard";
import { useTheme } from "@/composables/useTheme";
import { useMobile } from "@/composables/useMobile";
import { getOppositeLocale, setStoredLocale } from "@/i18n";
import type { Locale } from "@/i18n";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const store = useDashboardStore();
const theme = useTheme();
const { isMobile } = useMobile(899);
const sidebarOpen = ref(false);

// Close sidebar when switching back to desktop or navigating
watch(isMobile, (val) => { if (!val) sidebarOpen.value = false; });
watch(() => route.fullPath, () => { sidebarOpen.value = false; });

const { t, locale } = useI18n();

const themeIcon = computed(() => (theme.current.value === "dark" ? Sunny : Moon));

const localeLabel = computed(() =>
  locale.value === "zh-CN" ? "EN" : "中"
);

function switchLocale() {
  const next = getOppositeLocale(locale.value as Locale);
  locale.value = next;
  setStoredLocale(next);
}

const hostBadgeTone = computed(() => {
  if (store.hosts.length === 0) return "neutral";
  if (store.onlineCount === store.hosts.length) return "success";
  if (store.onlineCount > 0) return "warning";
  return "danger";
});

const currentHost = computed(() => {
  if (route.name !== "host-detail") return null;
  return store.hosts.find((item) => item.host_id === route.params.hostId) || null;
});

const navItems = computed(() => [
  { id: "dashboard", label: t("nav.dashboard"), path: "/", icon: House, badge: null },
  {
    id: "updates",
    label: t("nav.updates"),
    path: "/updates",
    icon: Warning,
    badge: store.updateCount,
    badgeTone: "danger",
  },
  { id: "audit", label: t("nav.audit"), path: "/audit", icon: List, badge: null },
  {
    id: "settings",
    label: t("nav.settings"),
    path: "/settings",
    icon: Setting,
    badge: null,
  },
  {
    id: "hosts",
    label: t("nav.hosts"),
    path: "/",
    icon: Collection,
    badge: store.hosts.length,
    badgeTone: hostBadgeTone.value,
  },
]);

const pageTitle = computed(() => {
  if (route.name === "host-detail") {
    return currentHost.value?.display_name || String(route.params.hostId || "Host");
  }
  if (route.name === "updates") return t("nav.updates");
  if (route.name === "audit") return t("nav.audit");
  if (route.name === "settings") return t("nav.settings");
  return t("nav.dashboard");
});

const isDragging = ref(false);

const getInitialWidth = () => {
  if (typeof window !== "undefined") {
    const stored = localStorage.getItem("fleetge_sidebar_width");
    if (stored) {
      const w = parseInt(stored, 10);
      if (!isNaN(w) && w >= 180 && w <= 450) {
        return w;
      }
    }
  }
  return 260;
};

const sidebarWidth = ref(getInitialWidth());

function handleMouseMove(e: MouseEvent) {
  if (!isDragging.value) return;
  const newWidth = Math.max(180, Math.min(450, e.clientX));
  sidebarWidth.value = newWidth;
}

function handleMouseUp() {
  if (!isDragging.value) return;
  isDragging.value = false;
  document.removeEventListener("mousemove", handleMouseMove);
  document.removeEventListener("mouseup", handleMouseUp);
  document.body.classList.remove("is-resizing-sidebar");
  localStorage.setItem("fleetge_sidebar_width", sidebarWidth.value.toString());
}

function startResize(e: MouseEvent) {
  e.preventDefault();
  isDragging.value = true;
  document.addEventListener("mousemove", handleMouseMove);
  document.addEventListener("mouseup", handleMouseUp);
  document.body.classList.add("is-resizing-sidebar");
}

onMounted(() => {
  store.startPolling(15000);
});

onUnmounted(() => {
  store.stopPolling();
  document.removeEventListener("mousemove", handleMouseMove);
  document.removeEventListener("mouseup", handleMouseUp);
  document.body.classList.remove("is-resizing-sidebar");
});

function isActive(id: string, path: string) {
  if (id === "hosts") return route.name === "host-detail";
  if (path === "/") return route.name === "dashboard";
  return route.path.startsWith(path);
}
function logout() {
  auth.logout();
  router.push("/login");
}
</script>

<style scoped>
.ops-shell {
  min-height: 100vh;
  display: grid;
  background: var(--surface-base);
  color: var(--text-primary);
}

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

.ops-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 0 8px 15px;
  border-bottom: 1px solid var(--border-subtle);
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
  font-weight: 800;
  margin: 0;
}

.ops-section-label,
.ops-topbar-kicker {
  color: var(--text-muted);
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.ops-nav,
.ops-host-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
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

.ops-nav-badge,
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

.ops-nav-badge.neutral {
  background: rgba(96, 165, 250, 0.14);
  color: var(--accent-blue);
}

.ops-nav-badge.success {
  background: rgba(52, 211, 153, 0.14);
  color: var(--success);
}

.ops-nav-badge.warning {
  background: rgba(251, 191, 36, 0.16);
  color: var(--warning);
}

.ops-nav-badge.danger {
  background: rgba(248, 113, 113, 0.14);
  color: var(--danger);
}

.ops-host-list {
  min-height: 0;
  overflow: auto;
}

.ops-section-label {
  padding: 0 10px 4px;
}

.ops-host-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ops-main {
  min-width: 0;
  height: 100vh;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.ops-topbar {
  position: sticky;
  top: 0;
  z-index: 10;
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 24px;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--topbar-bg);
  backdrop-filter: blur(14px);
}

.ops-topbar-title {
  margin: 2px 0 0;
  font-size: 21px;
  line-height: 1.2;
}

.ops-topbar-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  min-width: 0;
}

.ops-host-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  padding-top: 2px;
}

.ops-topbar-right {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.ops-control {
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid var(--border-subtle);
  border-radius: 7px;
  background: var(--pill-bg);
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 600;
  line-height: 1;
  white-space: nowrap;
}

.ops-status-pill {
  min-width: 78px;
  padding: 0 10px;
  border-radius: 999px;
}

.ops-status-pill.warning {
  border-color: rgba(248, 113, 113, 0.35);
  background: rgba(248, 113, 113, 0.10);
  color: var(--danger);
}

.ops-health-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 12px rgba(52, 211, 153, 0.7);
}

.ops-content {
  flex: 1;
  min-width: 0;
  min-height: 0;
  padding: 16px 18px 20px;
  overflow: auto;
}

.ops-content.is-host-detail {
  overflow: hidden;
}

/* ── Hamburger button (hidden on desktop) ── */
.ops-mobile-menu-btn {
  display: none;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  background: var(--pill-bg);
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
  transition: background 160ms ease, color 160ms ease;
}

.ops-mobile-menu-btn:hover {
  background: var(--nav-hover-bg);
  color: var(--text-primary);
}

/* ── Mobile backdrop ── */
.ops-mobile-backdrop {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 90;
  background: rgba(0, 0, 0, 0.5);
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.ops-mobile-backdrop.is-visible {
  opacity: 1;
  pointer-events: auto;
}

.ops-sidebar-footer {
  display: none;
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--border-subtle);
  flex-direction: column;
  gap: 6px;
}

.ops-sidebar-footer-btn {
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

.ops-sidebar-footer-btn:hover {
  border-color: var(--border-strong);
  background: var(--nav-hover-bg);
  color: var(--text-primary);
}

.ops-sidebar-footer-btn .el-icon {
  width: 22px;
  height: 22px;
  margin-left: -2px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: var(--text-muted);
}

.ops-sidebar-footer-btn.logout:hover {
  border-color: rgba(248, 113, 113, 0.35);
  background: rgba(248, 113, 113, 0.08);
  color: var(--danger);
}

.ops-sidebar-footer-btn.logout:hover .el-icon {
  color: var(--danger);
}

@media (max-width: 899px) {
  .ops-shell {
    display: block;
  }

  .ops-mobile-menu-btn {
    display: inline-flex;
  }

  .ops-mobile-backdrop {
    display: block;
  }

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

  .ops-topbar-right .el-button {
    display: none !important;
  }

  .ops-main {
    height: auto;
    min-height: 100vh;
  }

  .ops-topbar {
    position: sticky;
    align-items: center;
    flex-direction: row;
    padding: 10px 14px;
    gap: 12px;
    min-height: 56px;
  }

  .ops-topbar-left {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 10px;
  }

  .ops-topbar-right {
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: 6px;
  }

  .ops-topbar-title {
    font-size: 17px;
  }

  .ops-host-tags {
    gap: 4px;
  }

  .ops-host-tags :deep(.el-tag) {
    font-size: 10px;
    height: 20px;
    padding: 0 4px;
  }

  .ops-content {
    overflow: visible;
    padding: 12px;
  }

  .ops-sidebar-resizer {
    display: none !important;
  }
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
</style>
