<template>
  <div class="ops-shell" :style="{ gridTemplateColumns: sidebarWidth + 'px minmax(0, 1fr)' }">
    <div class="ambient-aura" aria-hidden="true">
      <div class="aura-blob blob-1"></div>
      <div class="aura-blob blob-2"></div>
    </div>
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

        <!-- 主机管理一级标题与二级列表组 -->
        <div class="ops-nav-group">
          <div class="ops-nav-header">
            <button
              class="ops-nav-item"
              :class="{ active: route.name === 'settings' && route.query.section === 'hosts' }"
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
        </div>
      </nav>

      <div class="ops-sidebar-footer">
        <button class="ops-sidebar-footer-btn ops-sidebar-mobile-action" type="button" @click="switchLocale">
          <el-icon><Globe /></el-icon>
          <span>{{ localeLabel === '中' ? '简体中文' : 'English' }}</span>
        </button>
        <button class="ops-sidebar-footer-btn ops-sidebar-mobile-action" type="button" @click="theme.toggle()">
          <el-icon><component :is="themeIcon" /></el-icon>
          <span>{{ theme.current.value === 'dark' ? t('shell.switchLight') : t('shell.switchDark') }}</span>
        </button>
        <button class="ops-sidebar-footer-btn ops-sidebar-mobile-action" type="button" :disabled="store.manualLoading" @click="store.refreshAll">
          <el-icon><RefreshCw /></el-icon>
          <span>{{ t('shell.refresh') }}</span>
        </button>
        <button class="ops-sidebar-footer-btn ops-sidebar-mobile-action logout" type="button" @click="logout">
          <el-icon><LogOut /></el-icon>
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
              <Menu v-if="!sidebarOpen" />
              <X v-if="sidebarOpen" />
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
          <el-button
            class="ops-control ui-icon-button ops-desktop-tool"
            size="small"
            aria-label="EN/中"
            @click="switchLocale"
          >
            {{ localeLabel }}
          </el-button>
          <el-button
            class="ops-control ui-icon-button ops-desktop-tool"
            size="small"
            :icon="themeIcon"
            :aria-label="theme.current.value === 'dark' ? t('shell.switchLight') : t('shell.switchDark')"
            @click="theme.toggle()"
          />
          <el-button
            class="ops-control ui-icon-button ops-desktop-tool"
            size="small"
            :icon="RefreshCw"
            :loading="store.manualLoading"
            :aria-label="t('shell.refresh')"
            @click="store.refreshAll"
          />
          <el-button
            class="ops-control ui-button ui-button--compact ops-settings-topbar-btn"
            :class="{ active: route.name === 'settings' }"
            size="small"
            :aria-label="t('nav.settings')"
            @click="router.push({ name: 'settings' })"
          >
            <el-icon><Settings /></el-icon>
            {{ t('nav.settings') }}
          </el-button>
          <el-button class="ops-control ui-button ui-button--compact ui-button--muted ops-desktop-tool" size="small" @click="logout">
            <el-icon><LogOut /></el-icon>
            {{ t('shell.logout') }}
          </el-button>
        </div>
      </header>

      <main class="ops-content" :class="{ 'is-host-detail': route.name === 'host-detail' }">
        <slot />
      </main>
      <footer class="ops-footer">
        <span>{{ t('brand.name') }} v{{ appVersion }}</span>
        <span class="ops-footer-sep">·</span>
        <span>{{ t('footer.copyright', { year: currentYear }) }}</span>
        <span class="ops-footer-sep">·</span>
        <a href="https://github.com/VirgoooooX/fleetge" target="_blank" rel="noopener noreferrer" class="ops-footer-link">
          <el-icon><GitBranch /></el-icon>
          <span>{{ t('footer.github') }}</span>
        </a>
        <span class="ops-footer-sep">·</span>
        <a class="ops-footer-link" @click="router.push({ name: 'settings', query: { section: 'about' } })">
          <el-icon><BookOpen /></el-icon>
          <span>{{ t('footer.docs') }}</span>
        </a>
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import {
  Menu,
  X,
  Home,
  Moon,
  RefreshCw,
  Sun,
  LogOut,
  Settings,
  Globe,
  Grid,
  Plus,
  Server,
  Map as MapIcon,
  GitBranch,
  BookOpen,
} from "@lucide/vue";
import AppLogo from "@/components/AppLogo.vue";
import StatusIcon from "@/components/StatusIcon.vue";
import { useAuthStore } from "@/stores/auth";
import { useDashboardStore } from "@/stores/dashboard";
import { useTheme } from "@/composables/useTheme";
import { useMobile } from "@/composables/useMobile";
import { getOppositeLocale, setStoredLocale } from "@/i18n";
import type { Locale } from "@/i18n";

const appVersion = __APP_VERSION__;
const currentYear = new Date().getFullYear();

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

function applyRouteDemand() {
  if (route.name === "dashboard") {
    store.startPolling({ metrics: true, structureInterval: 30 });
  } else if (route.name === "host-detail") {
    store.startPolling({ metrics: true, structureInterval: 10 });
  } else if (route.name === "apps") {
    store.startPolling({ metrics: false, structureInterval: 10 });
  } else {
    store.stopPolling();
    void store.fetchHosts();
  }
}

watch(() => route.name, applyRouteDemand);

const { t, locale } = useI18n();

const themeIcon = computed(() => (theme.current.value === "dark" ? Sun : Moon));

const localeLabel = computed(() =>
  locale.value === "zh-CN" ? "EN" : "中"
);

function switchLocale() {
  const next = getOppositeLocale(locale.value as Locale);
  locale.value = next;
  setStoredLocale(next);
}

const currentHost = computed(() => {
  if (route.name !== "host-detail") return null;
  return store.hosts.find((item) => item.host_id === route.params.hostId) || null;
});

const navItems = computed(() => [
  { id: "dashboard", label: t("nav.dashboard"), path: "/", icon: Home, badge: null, badgeTone: null },
  { id: "fleet-map", label: t("nav.map"), path: "/map", icon: MapIcon, badge: null, badgeTone: null },
  { id: "apps", label: t("nav.apps"), path: "/apps", icon: Grid, badge: null, badgeTone: null },
]);

const pageTitle = computed(() => {
  if (route.name === "host-detail") {
    return currentHost.value?.display_name || String(route.params.hostId || "Host");
  }
  if (route.name === "settings") return t("nav.settings");
  if (route.name === "apps") return t("apps.title");
  if (route.name === "fleet-map") return t("nav.map");
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

let trackerMouseMove: ((e: MouseEvent) => void) | null = null;

onMounted(() => {
  applyRouteDemand();
  
  const shell = document.querySelector(".ops-shell") as HTMLElement;
  trackerMouseMove = (e: MouseEvent) => {
    if (shell) {
      shell.style.setProperty("--mouse-x", `${e.clientX}px`);
      shell.style.setProperty("--mouse-y", `${e.clientY}px`);
    }
  };
  window.addEventListener("mousemove", trackerMouseMove);
});

onUnmounted(() => {
  store.stopPolling();
  document.removeEventListener("mousemove", handleMouseMove);
  document.removeEventListener("mouseup", handleMouseUp);
  document.body.classList.remove("is-resizing-sidebar");
  if (trackerMouseMove) {
    window.removeEventListener("mousemove", trackerMouseMove);
  }
});

function isActive(id: string, path: string) {
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
  transition: all 160ms ease;
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

.ops-settings-topbar-btn.active {
  border-color: var(--nav-active-border) !important;
  background: var(--nav-active-bg) !important;
  color: var(--accent-blue) !important;
  box-shadow: var(--nav-active-shadow);
}

.ops-settings-topbar-btn {
  border-color: color-mix(in srgb, var(--accent-blue) 28%, transparent) !important;
  background: color-mix(in srgb, var(--accent-blue) 9%, var(--pill-bg)) !important;
  color: color-mix(in srgb, var(--accent-blue) 82%, var(--text-secondary)) !important;
}

.ops-settings-topbar-btn:hover,
.ops-settings-topbar-btn:focus-visible {
  border-color: color-mix(in srgb, var(--accent-blue) 46%, transparent) !important;
  background: color-mix(in srgb, var(--accent-blue) 15%, var(--pill-bg)) !important;
  color: var(--accent-blue) !important;
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
  padding: 16px 18px 4px;
  overflow: auto;
}

.ops-content.is-host-detail {
  overflow: hidden;
}

/* ── Footer ── */
.ops-footer {
  flex-shrink: 0;
  margin: 5px 0 7px;
  padding: 0 18px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-muted);
}

.ops-footer-sep {
  margin: 0 4px;
  color: var(--border-subtle);
  user-select: none;
}

.ops-footer-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-muted);
  text-decoration: none;
  cursor: pointer;
  transition: color 160ms ease;
}

.ops-footer-link:hover {
  color: var(--text-secondary);
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
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
  flex-direction: column;
  gap: 8px;
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

.ops-sidebar-footer-btn.active {
  border-color: var(--nav-active-border);
  background: var(--nav-active-bg);
  color: var(--text-primary);
  box-shadow: var(--nav-active-shadow);
}

.ops-sidebar-mobile-action {
  display: none;
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

  .ops-sidebar-mobile-action {
    display: flex;
  }

  .ops-desktop-tool {
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

.ops-main {
  position: relative;
  z-index: 1;
}

.ops-main::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(
    600px circle at var(--mouse-x, -1000px) var(--mouse-y, -1000px),
    rgba(99, 102, 241, 0.035),
    transparent 80%
  );
  z-index: 0;
}

/* Ambient Aura Background Styles */
.ambient-aura {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  overflow: hidden;
}

.ambient-aura .aura-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(140px);
  opacity: 0.04;
  mix-blend-mode: screen;
  animation: float-blob 25s infinite alternate ease-in-out;
  pointer-events: none;
}

[data-theme="light"] .ambient-aura .aura-blob {
  opacity: 0.02;
  mix-blend-mode: multiply;
}

.ambient-aura .blob-1 {
  width: 550px;
  height: 550px;
  background: radial-gradient(circle, var(--accent-blue, #3b82f6) 0%, transparent 80%);
  top: -10%;
  left: 20%;
  animation-duration: 30s;
}

.ambient-aura .blob-2 {
  width: 650px;
  height: 650px;
  background: radial-gradient(circle, var(--accent-cyan, #06b6d4) 0%, transparent 80%);
  bottom: -15%;
  right: 15%;
  animation-duration: 25s;
}

@keyframes float-blob {
  0% {
    transform: translate(0, 0) scale(1);
  }
  50% {
    transform: translate(80px, 45px) scale(1.08);
  }
  100% {
    transform: translate(-40px, 80px) scale(0.95);
  }
}
</style>
