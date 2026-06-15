<template>
  <div class="ops-shell">
    <aside class="ops-sidebar">
      <div class="ops-brand" @click="router.push('/')">
        <div class="ops-brand-mark">HD</div>
        <div>
          <div class="ops-brand-title">Host Dashboard</div>
          <div class="ops-brand-subtitle">Docker Ops Console</div>
        </div>
      </div>

      <nav class="ops-nav" aria-label="主导航">
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
        <div class="ops-section-label">Hosts</div>
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
    </aside>

    <div class="ops-main">
      <header class="ops-topbar">
        <div class="ops-topbar-left">
          <div class="ops-topbar-kicker">Operations</div>
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
            {{ store.onlineCount }}/{{ store.hosts.length }} 在线
          </div>
          <div class="ops-control ops-status-pill warning" v-if="store.updateCount > 0">
            {{ store.updateCount }} 更新
          </div>
          <el-button
            class="ops-control ops-icon-button"
            size="small"
            :icon="themeIcon"
            :aria-label="theme.current.value === 'dark' ? '切换浅色模式' : '切换深色模式'"
            @click="theme.toggle()"
          />
          <el-button
            class="ops-control ops-action-button"
            size="small"
            :loading="store.loading || store.updateLoading"
            @click="store.refreshAll"
          >
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
          <el-button class="ops-control ops-action-button muted" size="small" @click="logout">
            <el-icon><SwitchButton /></el-icon>
            退出
          </el-button>
        </div>
      </header>

      <main class="ops-content">
        <slot />
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  Collection,
  House,
  List,
  Moon,
  Refresh,
  Sunny,
  SwitchButton,
  Warning,
} from "@element-plus/icons-vue";
import StatusIcon from "@/components/StatusIcon.vue";
import { useAuthStore } from "@/stores/auth";
import { useDashboardStore } from "@/stores/dashboard";
import { useTheme } from "@/composables/useTheme";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const store = useDashboardStore();
const theme = useTheme();

const themeIcon = computed(() => (theme.current.value === "dark" ? Sunny : Moon));

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
  { id: "dashboard", label: "Dashboard", path: "/", icon: House, badge: null },
  {
    id: "updates",
    label: "Updates",
    path: "/updates",
    icon: Warning,
    badge: store.updateCount,
    badgeTone: "danger",
  },
  { id: "audit", label: "Audit", path: "/audit", icon: List, badge: null },
  {
    id: "hosts",
    label: "Hosts",
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
  if (route.name === "updates") return "镜像更新";
  if (route.name === "audit") return "操作审计";
  return "Dashboard";
});

onMounted(() => {
  store.startPolling(15000);
});

onUnmounted(() => {
  store.stopPolling();
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
  grid-template-columns: 260px minmax(0, 1fr);
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
  padding: 18px 14px;
  border-right: 1px solid var(--border-subtle);
  background: var(--sidebar-bg), var(--surface-raised);
}

.ops-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 8px 14px;
  border-bottom: 1px solid var(--border-subtle);
  cursor: pointer;
}

.ops-brand-mark {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(96, 165, 250, 0.5);
  border-radius: 8px;
  background: var(--sidebar-brand-bg);
  color: var(--accent-blue);
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 700;
}

.ops-brand-title {
  font-size: 14px;
  font-weight: 700;
}

.ops-brand-subtitle,
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

.ops-icon-button,
.ops-action-button {
  margin-left: 0 !important;
}

.ops-icon-button {
  width: 30px;
  padding: 0 !important;
}

.ops-action-button {
  min-width: 64px;
  padding: 0 10px !important;
}

.ops-action-button.muted {
  color: var(--text-muted);
}

.ops-action-button:hover,
.ops-icon-button:hover {
  border-color: var(--border-strong) !important;
  background: var(--nav-hover-bg) !important;
  color: var(--text-primary) !important;
}

.ops-health-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--success);
  box-shadow: 0 0 12px rgba(52, 211, 153, 0.7);
}

.ops-content {
  min-width: 0;
  padding: 22px 24px 32px;
}

@media (max-width: 900px) {
  .ops-shell {
    display: block;
  }

  .ops-sidebar {
    position: static;
    height: auto;
    padding: 12px;
    border-right: 0;
    border-bottom: 1px solid var(--border-subtle);
  }

  .ops-brand {
    padding-bottom: 10px;
  }

  .ops-nav,
  .ops-host-list {
    flex-direction: row;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .ops-section-label {
    display: none;
  }

  .ops-nav-item,
  .ops-host-link {
    width: auto;
    flex: 0 0 auto;
  }

  .ops-topbar {
    position: static;
    align-items: flex-start;
    flex-direction: column;
    padding: 14px 16px;
  }

  .ops-content {
    padding: 16px;
  }
}
</style>
