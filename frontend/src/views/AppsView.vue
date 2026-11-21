<template>
  <div class="apps-layout" v-loading="loading">
    <section class="apps-dashboard ui-dashboard-surface" :aria-label="t('apps.title')">
      <div class="apps-dashboard-copy ui-dashboard-copy">
        <h2 class="ui-dashboard-title">{{ t('apps.kicker') }}</h2>
        <p class="ui-dashboard-description">{{ t('apps.description') }}</p>
      </div>

      <div class="apps-operation-deck" role="group" :aria-label="t('apps.title')">
        <div class="apps-primary-actions">
          <div class="operation-cluster operation-cluster--search">
            <span class="operation-group-icon" aria-hidden="true">
              <el-icon><Search /></el-icon>
            </span>
            <el-input
              v-model="searchQuery"
              :placeholder="t('apps.searchPlaceholder')"
              :aria-label="t('apps.searchPlaceholder')"
              class="search-input"
              clearable
            />
          </div>

          <el-select v-model="filterHost" class="filter-select" :aria-label="t('apps.filter.allHosts')" :placeholder="t('apps.filter.allHosts')">
            <template #prefix>
              <el-icon><Link2 /></el-icon>
            </template>
            <el-option :label="t('apps.filter.allHosts')" value="" />
            <el-option v-for="h in uniqueHosts" :key="h.id" :label="h.name" :value="h.id" />
          </el-select>

          <div class="operation-cluster operation-cluster--view">
            <span class="operation-group-icon" aria-hidden="true">
              <el-icon><SlidersHorizontal /></el-icon>
            </span>
            <div class="view-options-track">
              <button
                type="button"
                class="view-action"
                :class="{ active: viewMode === 'group' }"
                :aria-pressed="viewMode === 'group'"
                @click="viewMode = 'group'"
              >
                <el-icon><Layers /></el-icon>
                <span>{{ t('apps.view.byGroup') }}</span>
              </button>

              <button
                type="button"
                class="view-action"
                :class="{ active: viewMode === 'host' }"
                :aria-pressed="viewMode === 'host'"
                @click="viewMode = 'host'"
              >
                <el-icon><Link2 /></el-icon>
                <span>{{ t('apps.view.byHost') }}</span>
              </button>

              <button
                type="button"
                class="view-action"
                :class="{ active: viewMode === 'all' }"
                :aria-pressed="viewMode === 'all'"
                @click="viewMode = 'all'"
              >
                <el-icon><LayoutGrid /></el-icon>
                <span>{{ t('apps.view.all') }}</span>
              </button>
            </div>
          </div>
        </div>

        <div class="apps-secondary-actions">
          <span class="operation-group-icon" aria-hidden="true">
            <el-icon><Filter /></el-icon>
          </span>
          <div role="group" class="apps-status-tabs" :aria-label="t('apps.title')">
            <button
              v-for="chip in statusChips"
              :key="chip.value"
              type="button"
              class="app-status-tab"
              :class="{ active: filterStatus === chip.value }"
              :aria-pressed="filterStatus === chip.value"
              @click="filterStatus = chip.value"
            >
              <span>{{ chip.label }}</span>
              <span v-if="chip.count > 0" class="app-status-count">{{ chip.count }}</span>
            </button>
          </div>

          <div class="checkbox-filters">
            <el-checkbox v-model="filterNoUrl" :label="t('apps.filter.noUrl')" />
          </div>

        </div>
      </div>
    </section>

    <!-- Error state -->
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      closable
      @close="error = ''"
      class="mb-4"
    />

    <!-- Categorized Grid Views -->
    <div class="apps-container">
      <!-- Empty state -->
      <el-empty v-if="filteredApps.length === 0" :description="t('apps.empty')" />

      <!-- View: By Group -->
      <template v-else-if="viewMode === 'group'">
        <section v-for="g in appsByGroup" :key="g.name" class="apps-section">
          <h3 class="section-title">
            <el-icon class="mr-2"><Layers /></el-icon>
            {{ g.name }}
            <span class="section-count">{{ g.apps.length }}</span>
          </h3>
          <div class="apps-grid">
            <AppTile
              v-for="app in g.apps"
              :key="`${app.host_id}-${app.stack_name}`"
              :app="app"
              :menu-open="!!menuAnchor && menuApp?.host_id === app.host_id && menuApp?.stack_name === app.stack_name"
              @launch="handleAppClick(app)"
              @menu="openAppMenu(app, $event)"
            />
          </div>
        </section>
      </template>

      <!-- View: By Host -->
      <template v-else-if="viewMode === 'host'">
        <section v-for="h in appsByHost" :key="h.id" class="apps-section">
          <h3 class="section-title host-section-title">
            <el-image
              v-if="h.logo"
              :src="theme.current.value === 'dark' ? h.logo.darkSrc : h.logo.src"
              class="host-section-logo"
              :class="{ 'is-wide': h.logo.isWide }"
              fit="contain"
              aria-hidden="true"
            >
              <template #error><el-icon><Link2 /></el-icon></template>
            </el-image>
            <el-icon v-else class="host-section-logo"><Link2 /></el-icon>
            <span class="host-section-name">{{ h.name }}</span>
            <span class="section-count">{{ h.apps.length }}</span>
          </h3>
          <div class="apps-grid">
            <AppTile
              v-for="app in h.apps"
              :key="`${app.host_id}-${app.stack_name}`"
              :app="app"
              :menu-open="!!menuAnchor && menuApp?.host_id === app.host_id && menuApp?.stack_name === app.stack_name"
              @launch="handleAppClick(app)"
              @menu="openAppMenu(app, $event)"
            />
          </div>
        </section>
      </template>

      <!-- View: All (No Categories) -->
      <template v-else>
        <div class="apps-grid u-mt-4">
          <AppTile
            v-for="app in filteredApps"
            :key="`${app.host_id}-${app.stack_name}`"
            :app="app"
            :menu-open="!!menuAnchor && menuApp?.host_id === app.host_id && menuApp?.stack_name === app.stack_name"
            @launch="handleAppClick(app)"
            @menu="openAppMenu(app, $event)"
          />
        </div>
      </template>
    </div>

    <AppContextMenu
      v-if="menuApp && menuAnchor"
      :app="menuApp"
      :anchor="menuAnchor"
      @close="menuAnchor = null"
      @command="executeAppCommand"
    />

    <!-- SSE Operations Dialog -->
    <el-dialog
      v-model="dockDialogVisible"
      :title="dockTitle"
      width="min(720px, calc(100vw - 24px))"
      class="ui-dialog"
      :close-on-click-modal="false"
      @close="operation.discard"
    >
      <div class="sse-dialog-body">
        <StackOperationDock
          v-if="dockDialogVisible && activeApp"
          :stack-name="activeApp.stack_name"
          :action="operationAction"
          :lines="terminalOutputs"
          :status="operationStatus"
          :message="operationMessage"
          @close="dockDialogVisible = false"
          @cancel="operation.cancel"
        />
      </div>
    </el-dialog>

    <AppProfilesDialog
      v-if="editProfileVisible"
      :key="selectedHostId"
      v-model="editProfileVisible"
      :host-id="selectedHostId"
      :host-name="selectedHostName"
      @saved="fetchApps({ silent: true })"
    />
  </div>
</template>

<script setup lang="ts">
import { copyText } from "@/utils/clipboard";
import { ref, shallowRef, computed, onMounted, onBeforeUnmount, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import {
  Filter,
  Layers,
  LayoutGrid,
  Link2,
  Search,
  SlidersHorizontal,
} from "@lucide/vue";
import { isRunning, listApps, type LauncherApp } from "@/api/apps";
import { useSseOperation } from "@/composables/useSseOperation";
import AppTile, { type AppMenuAnchor } from "@/components/apps/AppTile.vue";
import AppContextMenu, { type AppCommand } from "@/components/apps/AppContextMenu.vue";
import { useDashboardStore } from "@/stores/dashboard";
import { useTheme } from "@/composables/useTheme";
import { resolveHostLogo } from "@/utils/hostLogo";
import StackOperationDock from "@/components/StackOperationDock.vue";
import AppProfilesDialog from "@/components/AppProfilesDialog.vue";

const router = useRouter();
const route = useRoute();
const dashboardStore = useDashboardStore();
const theme = useTheme();
const { t } = useI18n();

// Component data
const rawApps = ref<LauncherApp[]>([]);
const loading = ref(false);
const error = ref("");

// Filters state
const searchQuery = ref("");
const filterHost = ref("");
const filterStatus = ref("");
const filterNoUrl = ref(false);
const storedViewMode = localStorage.getItem("apps_view_mode");
const viewMode = ref(storedViewMode === "host" || storedViewMode === "all" ? storedViewMode : "group");

watch(viewMode, (newVal) => {
  localStorage.setItem("apps_view_mode", newVal);
});

const routeStatusFilters = new Set(["", "running", "error", "updatable", "no-url"]);

watch(
  () => [route.query.status, route.query.host] as const,
  ([statusVal, hostVal]) => {
    const nextStatus = Array.isArray(statusVal) ? statusVal[0] : statusVal;
    filterStatus.value = typeof nextStatus === "string" && routeStatusFilters.has(nextStatus) ? nextStatus : "";
    const nextHost = Array.isArray(hostVal) ? hostVal[0] : hostVal;
    filterHost.value = typeof nextHost === "string" ? nextHost : "";
  },
  { immediate: true },
);

// SSE Dock Dialog state
const dockDialogVisible = ref(false);
const activeApp = ref<LauncherApp | null>(null);
const operationAction = ref("");
const operationStatus = ref<"running" | "success" | "error" | "idle">("idle");
const operationMessage = ref("");
const terminalOutputs = ref<string[]>([]);
const operation = useSseOperation();
const menuAnchor = shallowRef<AppMenuAnchor | null>(null);
const menuTarget = ref<{ hostId: string; stackName: string } | null>(null);

// App Profile Edit state
const editProfileVisible = ref(false);
const selectedHostId = ref("");
const selectedHostName = ref("");

let listRequest: AbortController | null = null;

async function fetchApps(options: { silent?: boolean } = {}) {
  listRequest?.abort();
  const request = new AbortController();
  listRequest = request;
  if (!options.silent) loading.value = true;
  error.value = "";
  try {
    const apps = await listApps(request.signal);
    if (!request.signal.aborted) rawApps.value = apps;
  } catch (err: any) {
    if (!request.signal.aborted) error.value = err.response?.data?.detail || err.message || "Failed to fetch launcher apps";
  } finally {
    if (listRequest === request) {
      listRequest = null;
      loading.value = false;
    }
  }
}

const liveHostsById = computed(() => new Map(dashboardStore.hosts.map(host => [host.host_id, host])));

const appsWithLiveHostState = computed(() =>
  rawApps.value.map((app) => {
    const host = liveHostsById.value.get(app.host_id);
    if (!host) return app;
    return {
      ...app,
      host_name: host.display_name || app.host_name,
      host_status: host.status || app.host_status,
    };
  })
);

// Compute Host options from loaded apps
const uniqueHosts = computed(() => {
  const map = new Map<string, string>();
  appsWithLiveHostState.value.forEach(app => {
    if (app.host_id && app.host_name) {
      map.set(app.host_id, app.host_name);
    }
  });
  return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
});

// Compute Status counts for filter chips
const statusChips = computed(() => {
  const apps = appsWithLiveHostState.value;
  return [
    { value: "", label: t("apps.chip.all"), count: apps.length },
    { value: "running", label: t("apps.chip.running"), count: apps.filter(a => isRunning(a.status)).length },
    { value: "error", label: t("apps.chip.error"), count: apps.filter(a => a.status === "error" || a.status === "failed").length },
    { value: "updatable", label: t("apps.chip.updatable"), count: apps.filter(a => a.update_status === "updatable").length },
    { value: "no-url", label: t("apps.chip.noUrl"), count: apps.filter(a => !a.app_url).length },
  ];
});

// Primary filtering logic
const filteredApps = computed(() => {
  return appsWithLiveHostState.value.filter(app => {
    // Search filter (title, stack name, group)
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.toLowerCase().trim();
      const matchTitle = app.title && app.title.toLowerCase().includes(q);
      const matchStack = app.stack_name && app.stack_name.toLowerCase().includes(q);
      const matchGroup = app.group && app.group.toLowerCase().includes(q);
      if (!matchTitle && !matchStack && !matchGroup) return false;
    }

    // Host filter
    if (filterHost.value && app.host_id !== filterHost.value) {
      return false;
    }

    // Status filter
    if (filterStatus.value) {
      if (filterStatus.value === "running") {
        if (!isRunning(app.status)) return false;
      } else if (filterStatus.value === "error") {
        if (app.status !== "error" && app.status !== "failed") return false;
      } else if (filterStatus.value === "updatable") {
        if (app.update_status !== "updatable") return false;
      } else if (filterStatus.value === "no-url") {
        if (app.app_url) return false;
      }
    }

    // No-URL filter checkbox (hide apps with no URL config)
    if (filterNoUrl.value && !app.app_url) {
      return false;
    }

    return true;
  });
});

// Group apps dynamically
const appsByGroup = computed(() => {
  const groups = new Map<string, LauncherApp[]>();
  filteredApps.value.forEach(app => {
    const gName = app.group ? app.group.trim() : "Other";
    const groupApps = groups.get(gName);
    if (groupApps) groupApps.push(app);
    else groups.set(gName, [app]);
  });
  return [...groups.keys()].sort().map(name => ({ name, apps: groups.get(name)! }));
});

// Group apps by host dynamically
const appsByHost = computed(() => {
  const hosts = new Map<string, { name: string; apps: LauncherApp[] }>();
  filteredApps.value.forEach(app => {
    const host = hosts.get(app.host_id);
    if (host) host.apps.push(app);
    else hosts.set(app.host_id, { name: app.host_name || app.host_id, apps: [app] });
  });

  // Get host IDs ordered as in dashboardStore.hosts
  const orderedHostIds = dashboardStore.hosts.map(h => h.host_id);

  return [...hosts.keys()]
    .sort((a, b) => {
      const indexA = orderedHostIds.indexOf(a);
      const indexB = orderedHostIds.indexOf(b);
      if (indexA === -1 && indexB === -1) return a.localeCompare(b);
      if (indexA === -1) return 1;
      if (indexB === -1) return -1;
      return indexA - indexB;
    })
    .map(id => ({
      id, ...hosts.get(id)!,
      logo: resolveHostLogo(liveHostsById.value.get(id)?.logo),
    }));
});

const menuApp = computed(() => filteredApps.value.find(app =>
  app.host_id === menuTarget.value?.hostId && app.stack_name === menuTarget.value?.stackName,
));

function openAppMenu(app: LauncherApp, anchor: AppMenuAnchor) {
  menuTarget.value = { hostId: app.host_id, stackName: app.stack_name };
  menuAnchor.value = anchor;
}

watch([viewMode, menuApp], ([mode, app], [previousMode]) => {
  if (!app || mode !== previousMode) menuAnchor.value = null;
});

function openDashboard(app: LauncherApp) {
  void router.push({ name: "host-detail", params: { hostId: app.host_id }, query: { stack: app.stack_name } });
}

function handleAppClick(app: LauncherApp) {
  if (app.app_url) window.open(app.app_url, "_blank", "noopener,noreferrer");
  else openDashboard(app);
}

async function executeAppCommand(cmd: AppCommand) {
  const app = menuApp.value;
  if (!app) return;
  if (cmd === "open-dashboard") {
    openDashboard(app);
  } else if (cmd === "copy-url") {
    if (!app.app_url) return;
    try {
      await copyText(app.app_url);
      ElMessage.success(t("stackOp.copied"));
    } catch {
      ElMessage.warning(t("stackOp.copyFailed"));
    }
  } else if (cmd === "edit-profile") {
    openAppProfileDialogForHost(app.host_id, app.host_name);
  } else {
    void startSseOperation(cmd, app);
  }
}

// SSE Stack Operations
const dockTitle = computed(() => {
  if (!operationAction.value) return "";
  const keyMap: Record<string, string> = {
    start: "stackOp.starting",
    stop: "stackOp.stopping",
    restart: "stackOp.restarting",
  };
  return t(keyMap[operationAction.value] || "stackOp.operation");
});

async function startSseOperation(action: string, app: LauncherApp) {
  activeApp.value = app;
  operationAction.value = action;
  operationStatus.value = "running";
  const label = t(`stack.action.${action}`);
  operationMessage.value = t("stack.confirm.running", { action: label });
  terminalOutputs.value = [];
  dockDialogVisible.value = true;

  const result = await operation.run({
    hostId: app.host_id,
    stackName: app.stack_name,
    action,
    cols: 110,
    rows: 24,
    timeoutMs: 180000,
    onChunk: chunk => terminalOutputs.value.push(chunk),
  });
  if (!result) return;
  const success = result.kind === "complete" && result.success;
  operationStatus.value = success ? "success" : "error";
  if (result.kind === "timeout") operationMessage.value = t("stack.confirm.timeout");
  else if (result.kind === "cancelled") operationMessage.value = t("stack.confirm.cancelled");
  else if (result.kind === "no-result") operationMessage.value = t("stack.confirm.noResult");
  else operationMessage.value = ("message" in result && result.message) || t(success ? "stack.confirm.success" : "stack.confirm.failure", { action: label });
  if (result.kind === "complete") void fetchApps({ silent: true });
}

// Profile dialog functions
function openAppProfileDialogForHost(hostId: string, hostName: string) {
  selectedHostId.value = hostId;
  selectedHostName.value = hostName;
  editProfileVisible.value = true;
}

// Component lifecycle
onMounted(() => {
  void fetchApps();
  if (dashboardStore.hosts.length === 0) {
    void dashboardStore.fetchHosts();
  }
});

onBeforeUnmount(() => listRequest?.abort());
</script>

<style scoped>
.apps-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - 120px);
}

.apps-dashboard {
  --apps-control-height: 36px;
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(690px, 770px);
  align-items: center;
  gap: 32px;
  height: var(--ui-dashboard-header-height);
  min-height: var(--ui-dashboard-header-height);
  padding: var(--ui-dashboard-header-padding-block) var(--ui-dashboard-header-padding-inline);
  background:
    linear-gradient(110deg, color-mix(in srgb, var(--accent-blue) 7%, transparent), transparent 32%),
    var(--ui-dashboard-bg);
}

.apps-dashboard-copy {
  min-width: 0;
}

.apps-dashboard-copy .ui-dashboard-description {
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.apps-operation-deck {
  display: grid;
  width: min(100%, 770px);
  min-width: 0;
  justify-self: end;
  gap: 12px;
}

.apps-primary-actions,
.apps-secondary-actions {
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.apps-primary-actions {
  display: grid;
  grid-template-columns: minmax(220px, 280px) 140px minmax(320px, 1fr);
}

.apps-secondary-actions {
  display: flex;
  width: 100%;
}

.operation-cluster {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.operation-group-icon {
  display: inline-flex;
  box-sizing: border-box;
  width: 36px;
  height: var(--apps-control-height);
  flex: 0 0 36px;
  align-items: center;
  justify-content: flex-start;
  margin: 0 2px;
  padding: 0 10px 0 4px;
  border: 0;
  border-right: 1px solid color-mix(in srgb, var(--border-subtle) 82%, transparent);
  background: transparent;
  color: color-mix(in srgb, var(--text-primary) 76%, var(--accent-blue));
  font-size: 18px;
}

.operation-group-icon :deep(svg path) {
  stroke: currentColor;
  stroke-width: 0.55px;
  stroke-linejoin: round;
}

.search-input {
  width: auto;
  flex: 1 1 auto;
  min-width: 0;
}

.filter-select {
  width: 140px;
}

/* Apply global tokens to Element Plus Inputs, Selects, and Radios */
.search-input :deep(.el-input__wrapper),
.filter-select :deep(.el-select__wrapper) {
  background: var(--ui-control-bg) !important;
  border: 1px solid var(--border-subtle) !important;
  border-radius: var(--ui-radius-md) !important;
  box-shadow: none !important;
  height: var(--apps-control-height);
  padding: 0 13px;
  transition: border-color 0.2s, background-color 0.2s;
}

.search-input :deep(.el-input__wrapper) {
  background: color-mix(in srgb, var(--surface-panel) 76%, transparent) !important;
}

.filter-select :deep(.el-select__wrapper) {
  height: var(--apps-control-height);
}

.search-input :deep(.el-input__wrapper:hover),
.search-input :deep(.el-input__wrapper.is-focus),
.filter-select :deep(.el-select__wrapper:hover),
.filter-select :deep(.el-select__wrapper.is-focus) {
  border-color: var(--accent-blue) !important;
  background: var(--ui-control-hover-bg) !important;
}

.view-action {
  display: inline-flex;
  height: 28px;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: var(--ui-radius-md);
  font-family: inherit;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease, color 160ms ease, box-shadow 160ms ease;
}

.view-action {
  min-width: 0;
  flex: 1 1 0;
  padding: 0 9px;
  border: 0;
  background: transparent;
  color: var(--text-secondary);
}

.view-options-track {
  display: flex;
  box-sizing: border-box;
  height: var(--apps-control-height);
  min-width: 0;
  flex: 1 1 auto;
  align-items: center;
  padding: 3px;
  border: 1px solid var(--border-subtle);
  border-radius: calc(var(--ui-radius-md) + 1px);
  background: color-mix(in srgb, var(--ui-control-bg) 82%, var(--surface-panel-raised));
}

.view-action:hover {
  color: var(--accent-blue);
  background: var(--ui-control-hover-bg);
}

.view-action.active {
  color: #ffffff;
  background: var(--accent-blue);
  box-shadow: 0 2px 6px color-mix(in srgb, var(--accent-blue) 18%, transparent);
}

.view-action:focus-visible,
.app-status-tab:focus-visible {
  outline: 2px solid color-mix(in srgb, var(--accent-blue) 72%, transparent);
  outline-offset: 2px;
}

.apps-status-tabs {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  flex: 1 1 auto;
  min-width: 0;
  height: var(--apps-control-height);
  align-items: center;
  gap: 8px;
  overflow: hidden;
  padding: 0;
}

.app-status-tab {
  position: relative;
  display: inline-flex;
  height: 100%;
  width: 100%;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 0 6px;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-sm);
  font-weight: 700;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 160ms ease, background-color 160ms ease, color 160ms ease;
}

.app-status-tab:hover,
.app-status-tab.active {
  color: var(--accent-blue);
  background: transparent;
}

.app-status-tab.active {
  box-shadow: none;
}

.app-status-tab.active::after {
  content: "";
  position: absolute;
  right: 12px;
  bottom: 0;
  left: 12px;
  height: 2px;
  border-radius: 2px;
  background: var(--accent-blue);
}

.app-status-count {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  font-weight: 700;
}

.app-status-tab.active .app-status-count {
  color: var(--accent-blue);
}

.checkbox-filters {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  height: var(--apps-control-height);
  margin-left: auto;
  padding: 0 2px;
  border: 0;
  border-radius: 0;
  background: transparent;
  white-space: nowrap;
}

.checkbox-filters :deep(.el-checkbox__label) {
  color: var(--text-secondary);
  font-size: var(--text-sm);
}

.apps-container {
  display: flex;
  flex-direction: column;
  gap: 28px;
  width: 100%;
}

.apps-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.section-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0;
  display: flex;
  align-items: center;
}

.section-count {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  padding: 1px 6px;
  border-radius: 99px;
  margin-left: 8px;
}

.host-section-title {
  gap: 10px;
  min-height: 32px;
  font-size: 18px;
  font-weight: 800;
}

.host-section-logo {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  font-size: 24px;
}

.host-section-logo.is-wide {
  width: 72px;
}

.host-section-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.host-section-title .section-count {
  flex-shrink: 0;
  margin-left: 0;
}

.apps-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  grid-auto-rows: 80px;
  gap: 12px;
}

.mb-4 {
  margin-bottom: 16px;
}

.mr-2 {
  margin-right: 8px;
}

@media (max-width: 1260px) {
  .apps-dashboard {
    height: auto;
    grid-template-columns: 1fr;
    gap: 14px;
  }

  .apps-dashboard-copy .ui-dashboard-description {
    max-width: 560px;
  }

  .apps-operation-deck {
    justify-self: end;
  }
}

@media (max-width: 768px) {
  .apps-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .apps-dashboard {
    padding: var(--ui-dashboard-header-padding-block) var(--ui-dashboard-header-padding-inline);
  }

  .apps-operation-deck {
    width: 100%;
    justify-self: stretch;
  }

  .apps-primary-actions {
    grid-template-columns: minmax(0, 1fr);
    align-items: stretch;
  }

  .operation-cluster--search,
  .operation-cluster--view {
    width: 100%;
  }

  .filter-select {
    width: 100%;
  }

  .view-action {
    min-width: 0;
    padding: 0 10px;
  }

  .apps-secondary-actions {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
  }

  .apps-status-tabs {
    width: 100%;
  }

  .checkbox-filters {
    grid-column: 2;
    margin-left: 0;
    justify-self: end;
  }
}

@media (max-width: 520px) {
  .operation-cluster--view {
    gap: 6px;
  }

  .view-action {
    padding: 0 7px;
  }
}
@media (prefers-reduced-motion: reduce) {
  .view-action,
  .app-status-tab {
    transition: none;
  }
}
</style>
