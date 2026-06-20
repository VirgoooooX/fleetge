<template>
  <div class="apps-layout" v-loading="loading">
    <!-- Header with controls -->
    <header class="ui-page-header">
      <div class="header-left">
        <div class="ui-section-kicker">{{ t('apps.title') }}</div>
        <h2 class="ui-page-title">{{ t('apps.title') }}</h2>
      </div>
      
      <div class="header-right">
        <!-- Search -->
        <el-input
          v-model="searchQuery"
          :placeholder="t('apps.searchPlaceholder')"
          class="search-input"
          clearable
          :prefix-icon="Search"
        />

        <!-- Host selector -->
        <el-select v-model="filterHost" class="filter-select" :placeholder="t('apps.filter.allHosts')">
          <template #prefix>
            <el-icon><Link /></el-icon>
          </template>
          <el-option :label="t('apps.filter.allHosts')" value="" />
          <el-option v-for="h in uniqueHosts" :key="h.id" :label="h.name" :value="h.id" />
        </el-select>

        <!-- View mode -->
        <el-radio-group v-model="viewMode" size="default" class="view-mode-group">
          <el-radio-button label="group">
            <el-icon class="mr-1"><Collection /></el-icon>
            {{ t('apps.view.byGroup') }}
          </el-radio-button>
          <el-radio-button label="host">
            <el-icon class="mr-1"><Link /></el-icon>
            {{ t('apps.view.byHost') }}
          </el-radio-button>
          <el-radio-button label="all">
            <el-icon class="mr-1"><Grid /></el-icon>
            {{ t('apps.view.all') }}
          </el-radio-button>
        </el-radio-group>
      </div>
    </header>

    <!-- Filter chips bar -->
    <section class="filters-chips-bar">
      <div class="chips-list">
        <button
          v-for="chip in statusChips"
          :key="chip.value"
          type="button"
          class="filter-chip"
          :class="{ active: filterStatus === chip.value }"
          @click="filterStatus = chip.value"
        >
          <span>{{ chip.label }}</span>
          <span class="chip-count" v-if="chip.count > 0">{{ chip.count }}</span>
        </button>
      </div>

      <div class="checkbox-filters">
        <el-checkbox v-model="filterNoUrl" :label="t('apps.filter.noUrl')" />
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
    <main class="apps-container">
      <!-- Empty state -->
      <el-empty v-if="filteredApps.length === 0" :description="t('apps.empty')" />

      <!-- View: By Group -->
      <template v-else-if="viewMode === 'group'">
        <section v-for="g in appsByGroup" :key="g.name" class="apps-section">
          <h3 class="section-title">
            <el-icon class="mr-2"><Collection /></el-icon>
            {{ g.name }}
            <span class="section-count">{{ g.apps.length }}</span>
          </h3>
          <div class="apps-grid">
            <div
              v-for="app in g.apps"
              :key="`${app.host_id}-${app.stack_name}`"
              class="app-tile"
              @click="handleAppClick(app)"
              @contextmenu="handleContextMenu($event, app)"
            >
              <div class="app-icon-wrap">
                <el-image v-if="app.icon_url" :src="getIconUrl(app.icon_url)" class="app-icon-img" fit="contain">
                  <template #error>
                    <el-icon class="app-icon-fallback"><Picture /></el-icon>
                  </template>
                </el-image>
                <el-icon v-else class="app-icon-fallback"><FolderOpened /></el-icon>
                <span class="app-icon-update-dot" v-if="app.update_status === 'updatable'" :title="t('update.status.updatable')" />
              </div>
              <div class="app-info">
                <span class="app-title">{{ app.title || app.stack_name }}</span>
                <span class="app-meta">
                  <span class="dot-state" :class="`dot-${stackStatusType(app.status)}`" />
                  <span class="meta-text">
                    <span class="host-text">{{ app.host_name }}</span>
                    <span class="divider-dot">·</span>
                    <span class="count-text">{{ app.running_count }}/{{ app.service_count }}</span>
                  </span>
                </span>
              </div>
            </div>
          </div>
        </section>
      </template>

      <!-- View: By Host -->
      <template v-else-if="viewMode === 'host'">
        <section v-for="h in appsByHost" :key="h.id" class="apps-section">
          <h3 class="section-title">
            <el-icon class="mr-2"><Link /></el-icon>
            {{ h.name }}
            <span class="section-count">{{ h.apps.length }}</span>
          </h3>
          <div class="apps-grid">
            <div
              v-for="app in h.apps"
              :key="`${app.host_id}-${app.stack_name}`"
              class="app-tile"
              @click="handleAppClick(app)"
              @contextmenu="handleContextMenu($event, app)"
            >
              <div class="app-icon-wrap">
                <el-image v-if="app.icon_url" :src="getIconUrl(app.icon_url)" class="app-icon-img" fit="contain">
                  <template #error>
                    <el-icon class="app-icon-fallback"><Picture /></el-icon>
                  </template>
                </el-image>
                <el-icon v-else class="app-icon-fallback"><FolderOpened /></el-icon>
                <span class="app-icon-update-dot" v-if="app.update_status === 'updatable'" :title="t('update.status.updatable')" />
              </div>
              <div class="app-info">
                <span class="app-title">{{ app.title || app.stack_name }}</span>
                <span class="app-meta">
                  <span class="dot-state" :class="`dot-${stackStatusType(app.status)}`" />
                  <span class="meta-text">
                    <span class="host-text">{{ app.host_name }}</span>
                    <span class="divider-dot">·</span>
                    <span class="count-text">{{ app.running_count }}/{{ app.service_count }}</span>
                  </span>
                </span>
              </div>
            </div>
          </div>
        </section>
      </template>

      <!-- View: All (No Categories) -->
      <template v-else>
        <div class="apps-grid mt-4">
          <div
            v-for="app in filteredApps"
            :key="`${app.host_id}-${app.stack_name}`"
            class="app-tile"
            @click="handleAppClick(app)"
            @contextmenu="handleContextMenu($event, app)"
          >
            <div class="app-icon-wrap">
              <el-image v-if="app.icon_url" :src="getIconUrl(app.icon_url)" class="app-icon-img" fit="contain">
                <template #error>
                  <el-icon class="app-icon-fallback"><Picture /></el-icon>
                </template>
              </el-image>
              <el-icon v-else class="app-icon-fallback"><FolderOpened /></el-icon>
              <span class="app-icon-update-dot" v-if="app.update_status === 'updatable'" :title="t('update.status.updatable')" />
            </div>
            <div class="app-info">
              <span class="app-title">{{ app.title || app.stack_name }}</span>
              <span class="app-meta">
                <span class="dot-state" :class="`dot-${stackStatusType(app.status)}`" />
                <span class="meta-text">
                  <span class="host-text">{{ app.host_name }}</span>
                  <span class="divider-dot">·</span>
                  <span class="count-text">{{ app.running_count }}/{{ app.service_count }}</span>
                </span>
              </span>
            </div>
          </div>
        </div>
      </template>
    </main>

    <!-- Custom Context Menu Overlay -->
    <div
      v-if="contextMenuVisible"
      class="custom-context-menu"
      :style="{ top: contextMenuY + 'px', left: contextMenuX + 'px' }"
      @click.stop
    >
      <div class="context-item" @click="triggerAction('open-dashboard')">
        <el-icon><Monitor /></el-icon> <span>{{ t('apps.menu.openDashboard') }}</span>
      </div>
      <div class="context-item" :class="{ disabled: activeApp?.management_status === 'unmanaged' }" @click="triggerAction('restart')">
        <el-icon><Refresh /></el-icon> <span>{{ t('apps.menu.restartApp') }}</span>
      </div>
      <div v-if="activeApp && isRunning(activeApp.status)" class="context-item" :class="{ disabled: activeApp?.management_status === 'unmanaged' }" @click="triggerAction('stop')">
        <el-icon><VideoPause /></el-icon> <span>{{ t('apps.menu.stopApp') }}</span>
      </div>
      <div v-else class="context-item" :class="{ disabled: activeApp?.management_status === 'unmanaged' }" @click="triggerAction('start')">
        <el-icon><VideoPlay /></el-icon> <span>{{ t('apps.menu.startApp') }}</span>
      </div>
      <div class="context-item" :class="{ disabled: !activeApp?.app_url }" @click="triggerAction('copy-url')">
        <el-icon><DocumentCopy /></el-icon> <span>{{ t('apps.menu.copyUrl') }}</span>
      </div>
      <el-divider class="my-1" />
      <div class="context-item" @click="triggerAction('edit-profile')">
        <el-icon><Setting /></el-icon> <span>{{ t('apps.menu.editProfile') }}</span>
      </div>
    </div>

    <!-- SSE Operations Dialog -->
    <el-dialog
      v-model="dockDialogVisible"
      :title="dockTitle"
      width="720px"
      custom-class="ui-dialog"
      :close-on-click-modal="false"
      @close="stopOperation"
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
          @cancel="cancelOperation"
        />
      </div>
    </el-dialog>

    <!-- App Profile Edit Dialog -->
    <el-dialog
      v-model="editProfileVisible"
      :title="t('settings.appProfiles.title', { name: selectedHostName })"
      width="820px"
      custom-class="ui-dialog"
    >
      <div class="profile-edit-body" v-loading="profilesLoading">
        <div class="existing-profiles">
          <div class="section-kicker">{{ t('settings.appProfiles.existing') }}</div>
          <el-table :data="profilesList" stripe size="small" max-height="250px">
            <el-table-column :label="t('settings.appProfiles.col.pattern')" prop="stack_pattern" width="130">
              <template #default="{ row }">
                <code class="pattern-code">{{ row.stack_pattern }}</code>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.title')" prop="title" width="130" />
            <el-table-column :label="t('settings.appProfiles.col.url')" prop="app_url" min-width="150" show-overflow-tooltip />
            <el-table-column :label="t('settings.appProfiles.col.group')" prop="group" width="100" />
            <el-table-column :label="t('settings.appProfiles.col.icon')" width="80" align="center">
              <template #default="{ row }">
                <el-image v-if="row.icon_value" :src="getIconUrl(row.icon_value)" class="mini-profile-icon" fit="contain">
                  <template #error>
                    <el-icon><Picture /></el-icon>
                  </template>
                </el-image>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column :label="t('settings.appProfiles.col.actions')" width="110" align="center">
              <template #default="{ row, $index }">
                <el-button size="small" type="primary" :icon="Edit" circle @click="editProfileEntry(row)" />
                <el-button size="small" type="danger" :icon="Delete" circle @click="removeProfileEntry($index)" />
              </template>
            </el-table-column>
          </el-table>
        </div>

        <el-divider>{{ t('settings.appProfiles.addNew') }}</el-divider>

        <el-form :model="profileForm" label-position="top" class="profile-form" ref="profileFormRef" :rules="profileRules">
          <div class="profile-form-grid">
            <el-form-item :label="t('settings.appProfiles.form.pattern')" prop="stack_pattern">
              <el-input v-model="profileForm.stack_pattern" :placeholder="t('settings.appProfiles.form.patternPlaceholder')" />
            </el-form-item>
            <el-form-item :label="t('settings.appProfiles.form.title')" prop="title">
              <el-input v-model="profileForm.title" :placeholder="t('settings.appProfiles.form.titlePlaceholder')" />
            </el-form-item>
            <el-form-item :label="t('settings.appProfiles.form.url')" prop="app_url">
              <el-input v-model="profileForm.app_url" :placeholder="t('settings.appProfiles.form.urlPlaceholder')" />
            </el-form-item>
            <el-form-item :label="t('settings.appProfiles.form.group')" prop="group">
              <el-input v-model="profileForm.group" :placeholder="t('settings.appProfiles.form.groupPlaceholder')" />
            </el-form-item>
            <el-form-item :label="t('settings.appProfiles.form.source')" class="full-width">
              <el-radio-group v-model="profileForm.sourceType" size="small">
                <el-radio-button label="none">{{ t('apps.chip.all') }} (None)</el-radio-button>
                <el-radio-button label="url">{{ t('settings.appProfiles.form.remoteUrl') }}</el-radio-button>
                <el-radio-button label="local">{{ t('settings.appProfiles.form.localFile') }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            
            <el-form-item v-if="profileForm.sourceType === 'url'" :label="t('settings.appProfiles.form.remoteUrl')" prop="icon_url" class="full-width">
              <el-input v-model="profileForm.icon_url" placeholder="https://cdn.jsdelivr.net/.../logo.svg" />
            </el-form-item>

            <el-form-item v-else-if="profileForm.sourceType === 'local'" :label="t('settings.appProfiles.form.localFile')" class="full-width">
              <div class="local-picker-row">
                <el-select v-model="profileForm.icon_file" :placeholder="t('settings.appProfiles.form.localPlaceholder')" class="flex-1">
                  <el-option v-for="file in availableFiles" :key="file" :label="file" :value="file" />
                </el-select>
                <el-upload
                  action="#"
                  :auto-upload="false"
                  :show-file-list="false"
                  :on-change="handleIconUpload"
                  class="uploader"
                >
                  <el-button type="info" :icon="Upload" class="ui-button ui-button--muted">{{ t('settings.appProfiles.form.upload') }}</el-button>
                </el-upload>
              </div>
            </el-form-item>
          </div>

          <div class="profile-add-row">
            <el-button type="primary" class="ui-button ui-button--compact" @click="addProfileEntry">
              {{ isEditMode ? t('settings.appProfiles.form.updateBtn') : t('settings.appProfiles.form.addBtn') }}
            </el-button>
          </div>
        </el-form>
      </div>

      <template #footer>
        <div class="dialog-actions-row">
          <el-button @click="editProfileVisible = false">{{ t('compose.cancel') }}</el-button>
          <el-button type="primary" @click="submitAppProfiles" :loading="store.saving">{{ t('settings.appProfiles.form.saveBtn') }}</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, reactive, onMounted, onUnmounted, watch } from "vue";
import { useRouter } from "vue-router";
import { useI18n } from "vue-i18n";
import { ElMessage } from "element-plus";
import type { FormInstance, FormRules } from "element-plus";
import {
  Search,
  Collection,
  Monitor,
  VideoPlay,
  VideoPause,
  Refresh,
  DocumentCopy,
  Setting,
  More,
  Picture,
  FolderOpened,
  Link,
  Upload,
  Delete,
  Grid,
  Edit,
} from "@element-plus/icons-vue";
import { apiClient } from "@/api/client";
import { streamSse } from "@/api/sse";
import { useSettingsStore, type AppProfileEntry } from "@/stores/settings";
import { useDashboardStore } from "@/stores/dashboard";
import StackOperationDock from "@/components/StackOperationDock.vue";
import UpdateBadge from "@/components/UpdateBadge.vue";

const router = useRouter();
const store = useSettingsStore();
const dashboardStore = useDashboardStore();
const { t } = useI18n();

// Component data
const rawApps = ref<any[]>([]);
const loading = ref(false);
const error = ref("");

// Filters state
const searchQuery = ref("");
const filterHost = ref("");
const filterStatus = ref("");
const filterNoUrl = ref(false);
const viewMode = ref<"group" | "host" | "all">(
  (localStorage.getItem("apps_view_mode") as any) || "group"
);

watch(viewMode, (newVal) => {
  localStorage.setItem("apps_view_mode", newVal);
});

// SSE Dock Dialog state
const dockDialogVisible = ref(false);
const activeApp = ref<any>(null);
const operationAction = ref("");
const operationStatus = ref<"running" | "success" | "error" | "idle">("idle");
const operationMessage = ref("");
const terminalOutputs = ref<string[]>([]);
let sseController: AbortController | null = null;

// Context Menu state
const contextMenuVisible = ref(false);
const contextMenuX = ref(0);
const contextMenuY = ref(0);

// App Profile Edit state
const editProfileVisible = ref(false);
const selectedHostId = ref("");
const selectedHostName = ref("");
const profilesLoading = ref(false);
const profilesList = ref<AppProfileEntry[]>([]);
const availableFiles = ref<string[]>([]);
const profileFormRef = ref<FormInstance>();
const profileForm = reactive({
  stack_pattern: "",
  title: "",
  app_url: "",
  group: "",
  sourceType: "none",
  icon_url: "",
  icon_file: "",
});

const validateHttpUrl = (_rule: any, value: string, callback: any) => {
  if (value && !/^https?:\/\//.test(value)) {
    callback(new Error(t("settings.hosts.form.invalid.url")));
  } else {
    callback();
  }
};

const profileRules = reactive<FormRules>({
  stack_pattern: [{ required: true, message: t("settings.icons.required.pattern"), trigger: "blur" }],
  app_url: [{ validator: validateHttpUrl, trigger: "blur" }],
  icon_url: [{ validator: validateHttpUrl, trigger: "blur" }],
});

// Fetch apps aggregator from API
async function fetchApps(options: { silent?: boolean } = {}) {
  if (!options.silent) {
    loading.value = true;
  }
  error.value = "";
  try {
    const res = await apiClient.get("/api/apps");
    rawApps.value = res.data || [];
  } catch (err: any) {
    error.value = err.response?.data?.detail || err.message || "Failed to fetch launcher apps";
  } finally {
    if (!options.silent) {
      loading.value = false;
    }
  }
}

// Compute Host options from loaded apps
const uniqueHosts = computed(() => {
  const map = new Map<string, string>();
  rawApps.value.forEach(app => {
    if (app.host_id && app.host_name) {
      map.set(app.host_id, app.host_name);
    }
  });
  return Array.from(map.entries()).map(([id, name]) => ({ id, name }));
});

// Compute Status counts for filter chips
const statusChips = computed(() => {
  const apps = rawApps.value;
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
  return rawApps.value.filter(app => {
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
  const groups: Record<string, any[]> = {};
  filteredApps.value.forEach(app => {
    const gName = app.group ? app.group.trim() : "Other";
    if (!groups[gName]) groups[gName] = [];
    groups[gName].push(app);
  });
  return Object.keys(groups)
    .sort()
    .map(name => ({ name, apps: groups[name] }));
});

// Group apps by host dynamically
const appsByHost = computed(() => {
  const hosts: Record<string, { name: string; apps: any[] }> = {};
  filteredApps.value.forEach(app => {
    if (!hosts[app.host_id]) {
      hosts[app.host_id] = { name: app.host_name || app.host_id, apps: [] };
    }
    hosts[app.host_id].apps.push(app);
  });

  // Get host IDs ordered as in dashboardStore.hosts
  const orderedHostIds = dashboardStore.hosts.map(h => h.host_id);

  return Object.keys(hosts)
    .sort((a, b) => {
      const indexA = orderedHostIds.indexOf(a);
      const indexB = orderedHostIds.indexOf(b);
      if (indexA === -1 && indexB === -1) return a.localeCompare(b);
      if (indexA === -1) return 1;
      if (indexB === -1) return -1;
      return indexA - indexB;
    })
    .map(id => ({ id, name: hosts[id].name, apps: hosts[id].apps }));
});

// Helpers
function isRunning(status: string) {
  return status === "running" || status === "active";
}

function stackStatusType(status: string): string {
  if (status === "running" || status === "active") return "running";
  if (status === "exited") return "exited";
  if (status === "stopped" || status === "inactive") return "stopped";
  return "partial";
}



function getIconUrl(value: string | null) {
  if (!value) return "";
  if (/^https?:\/\//.test(value)) return value;
  if (value.startsWith("/api/") || value.startsWith("/")) return value;
  return `/api/static/icons/${value}`;
}

// App actions
function handleAppClick(app: any) {
  if (app.app_url) {
    window.open(app.app_url, "_blank");
  } else {
    // Navigate to host detail page focused on the stack
    router.push({
      name: "host-detail",
      params: { hostId: app.host_id },
      query: { stack: app.stack_name }
    });
  }
}

// Custom Context Menu handlers
function handleContextMenu(e: MouseEvent, app: any) {
  e.preventDefault();
  activeApp.value = app;
  contextMenuX.value = e.clientX;
  contextMenuY.value = e.clientY;
  contextMenuVisible.value = true;
  document.addEventListener("click", closeContextMenu, { once: true });
}

function closeContextMenu() {
  contextMenuVisible.value = false;
}

function triggerAction(cmd: string) {
  closeContextMenu();
  if (activeApp.value) {
    executeAppCommand(cmd, activeApp.value);
  }
}

function executeAppCommand(cmd: string, app: any) {
  activeApp.value = app;
  if (cmd === "open-dashboard") {
    router.push({
      name: "host-detail",
      params: { hostId: app.host_id },
      query: { stack: app.stack_name }
    });
  } else if (cmd === "copy-url") {
    if (app.app_url) {
      navigator.clipboard.writeText(app.app_url);
      ElMessage.success(t("stackOp.copied"));
    }
  } else if (cmd === "edit-profile") {
    openAppProfileDialogForHost(app.host_id, app.host_name);
  } else if (cmd === "start" || cmd === "stop" || cmd === "restart") {
    startSseOperation(cmd, app);
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
  return t(keyMap[operationAction.value] || "kicker");
});

async function startSseOperation(action: string, app: any) {
  stopOperation();
  activeApp.value = app;
  operationAction.value = action;
  operationStatus.value = "running";
  operationMessage.value = t("stack.confirm.running", { action: t(`stack.action.${action}`) });
  terminalOutputs.value = [];
  dockDialogVisible.value = true;

  sseController = new AbortController();
  const label = t(`stack.action.${action}`);

  try {
    const url = `/api/hosts/${app.host_id}/stacks/${encodeURIComponent(app.stack_name)}/${action}?cols=110&rows=24`;
    await streamSse({
      url,
      method: "POST",
      signal: sseController.signal,
      timeoutMs: 180000,
      onTimeout: () => {
        operationStatus.value = "error";
        operationMessage.value = t("stack.confirm.timeout");
      },
      onEvent: (ev) => {
        if (ev.event === "chunk") {
          terminalOutputs.value.push(ev.data?.raw ?? ev.rawData);
        } else if (ev.event === "line") {
          terminalOutputs.value.push(ev.data?.text ?? ev.rawData);
        } else if (ev.event === "complete") {
          const success = ev.data?.status === "success";
          operationStatus.value = success ? "success" : "error";
          operationMessage.value = ev.data?.message || t(success ? "stack.confirm.success" : "stack.confirm.failure", { action: label });
          void fetchApps({ silent: true }); // Refresh statuses after operation finishes
        } else if (ev.event === "error") {
          operationStatus.value = "error";
          operationMessage.value = ev.data?.message || t("stack.confirm.failure", { action: label });
        }
      }
    });
  } catch (err: any) {
    if (sseController?.signal.aborted) return;
    operationStatus.value = "error";
    operationMessage.value = err.message || t("stack.confirm.failure", { action: label });
  }
}

function cancelOperation() {
  if (sseController) {
    sseController.abort();
    sseController = null;
  }
  operationStatus.value = "error";
  operationMessage.value = t("stack.confirm.cancelled");
}

function stopOperation() {
  cancelOperation();
  dockDialogVisible.value = false;
}

// Profile dialog functions
async function openAppProfileDialogForHost(hostId: string, hostName: string) {
  selectedHostId.value = hostId;
  selectedHostName.value = hostName;
  profilesList.value = [];
  availableFiles.value = [];
  
  profileForm.stack_pattern = "";
  profileForm.title = "";
  profileForm.app_url = "";
  profileForm.group = "";
  profileForm.sourceType = "none";
  profileForm.icon_url = "";
  profileForm.icon_file = "";

  editProfileVisible.value = true;
  profilesLoading.value = true;

  try {
    const res = await store.fetchAppProfiles(hostId);
    profilesList.value = res.profiles || [];
    availableFiles.value = res.available_files || [];
  } catch (err: any) {
    ElMessage.error(err || t("settings.appProfiles.fetchError"));
  } finally {
    profilesLoading.value = false;
  }
}

function removeProfileEntry(index: number) {
  profilesList.value.splice(index, 1);
}

function editProfileEntry(row: AppProfileEntry) {
  profileForm.stack_pattern = row.stack_pattern;
  profileForm.title = row.title || "";
  profileForm.app_url = row.app_url || "";
  profileForm.group = row.group || "";
  
  if (!row.icon_value) {
    profileForm.sourceType = "none";
    profileForm.icon_url = "";
    profileForm.icon_file = "";
  } else if (/^https?:\/\//.test(row.icon_value)) {
    profileForm.sourceType = "url";
    profileForm.icon_url = row.icon_value;
    profileForm.icon_file = "";
  } else {
    profileForm.sourceType = "local";
    profileForm.icon_url = "";
    profileForm.icon_file = row.icon_value;
  }
}

async function handleIconUpload(uploadFile: any) {
  const rawFile = uploadFile.raw;
  if (!rawFile) return;

  if (rawFile.size > 2 * 1024 * 1024) {
    ElMessage.error(t("settings.icons.upload.tooLarge"));
    return;
  }

  const loadingMsg = ElMessage({
    message: t("settings.icons.upload.progress"),
    duration: 0,
    type: "info",
  });

  try {
    const filename = await store.uploadIcon(selectedHostId.value, rawFile);
    loadingMsg.close();
    ElMessage.success(t("settings.icons.upload.success", { name: filename }));
    
    if (!availableFiles.value.includes(filename)) {
      availableFiles.value.push(filename);
      availableFiles.value.sort();
    }
    profileForm.icon_file = filename;
  } catch (e: any) {
    loadingMsg.close();
    ElMessage.error(e || t("settings.icons.upload.error"));
  }
}

const isEditMode = computed(() => {
  if (!profileForm.stack_pattern) return false;
  return profilesList.value.some(p => p.stack_pattern === profileForm.stack_pattern.trim());
});

async function addProfileEntry() {
  if (!profileFormRef.value) return;

  await profileFormRef.value.validate(async (valid) => {
    if (!valid) return;

    if (!profileForm.stack_pattern.trim()) {
      ElMessage.error(t("settings.icons.required.pattern"));
      return;
    }

    let iconVal: string | null = null;
    if (profileForm.sourceType === "url") {
      if (!profileForm.icon_url.trim()) {
        ElMessage.error(t("settings.icons.required.url"));
        return;
      }
      iconVal = profileForm.icon_url.trim();
    } else if (profileForm.sourceType === "local") {
      if (!profileForm.icon_file) {
        ElMessage.error(t("settings.icons.required.file"));
        return;
      }
      iconVal = profileForm.icon_file;
    }

    const dupIndex = profilesList.value.findIndex(p => p.stack_pattern === profileForm.stack_pattern.trim());
    const newEntry: AppProfileEntry = {
      stack_pattern: profileForm.stack_pattern.trim(),
      title: profileForm.title.trim() || null,
      app_url: profileForm.app_url.trim() || null,
      group: profileForm.group.trim() || null,
      icon_value: iconVal,
    };

    if (dupIndex > -1) {
      profilesList.value[dupIndex] = newEntry;
      ElMessage.info(t("settings.icons.mapping.updated", { pattern: profileForm.stack_pattern.trim() }));
    } else {
      profilesList.value.push(newEntry);
    }

    profileForm.stack_pattern = "";
    profileForm.title = "";
    profileForm.app_url = "";
    profileForm.group = "";
    profileForm.sourceType = "none";
    profileForm.icon_url = "";
    profileForm.icon_file = "";
  });
}

async function submitAppProfiles() {
  try {
    await store.saveAppProfiles(selectedHostId.value, profilesList.value);
    ElMessage.success(t("settings.appProfiles.saveSuccess", { name: selectedHostName.value }));
    editProfileVisible.value = false;
    void fetchApps({ silent: true }); // Refresh view
  } catch (err: any) {
    ElMessage.error(err || t("settings.appProfiles.saveError"));
  }
}

// Component lifecycle
onMounted(() => {
  void fetchApps();
  if (dashboardStore.hosts.length === 0) {
    void dashboardStore.fetchHosts();
  }
});

onUnmounted(() => {
  stopOperation();
});
</script>

<style scoped>
.apps-layout {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: calc(100vh - 120px);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.search-input {
  width: 220px;
}

.filter-select {
  width: 160px;
}

/* Apply global tokens to Element Plus Inputs, Selects, and Radios */
.search-input :deep(.el-input__wrapper),
.filter-select :deep(.el-select__wrapper) {
  background: var(--ui-control-bg) !important;
  border: 1px solid var(--border-subtle) !important;
  border-radius: var(--ui-radius-md) !important;
  box-shadow: none !important;
  height: 32px;
  padding: 0 12px;
  transition: border-color 0.2s, background-color 0.2s;
}

.search-input :deep(.el-input__wrapper:hover),
.search-input :deep(.el-input__wrapper.is-focus),
.filter-select :deep(.el-select__wrapper:hover),
.filter-select :deep(.el-select__wrapper.is-focus) {
  border-color: var(--accent-blue) !important;
  background: var(--ui-control-hover-bg) !important;
}

.view-mode-group :deep(.el-radio-button__inner) {
  background: var(--ui-control-bg) !important;
  border: 1px solid var(--border-subtle) !important;
  color: var(--text-secondary) !important;
  font-size: 12px;
  font-weight: 700;
  height: 32px;
  display: inline-flex;
  align-items: center;
  padding: 0 16px;
  border-radius: 0;
  transition: all 160ms ease;
}

.view-mode-group :deep(.el-radio-button:first-child .el-radio-button__inner) {
  border-top-left-radius: var(--ui-radius-md) !important;
  border-bottom-left-radius: var(--ui-radius-md) !important;
}

.view-mode-group :deep(.el-radio-button:last-child .el-radio-button__inner) {
  border-top-right-radius: var(--ui-radius-md) !important;
  border-bottom-right-radius: var(--ui-radius-md) !important;
}

.view-mode-group :deep(.el-radio-button__inner:hover) {
  color: var(--accent-blue) !important;
  background: var(--ui-control-hover-bg) !important;
  border-color: var(--accent-blue) !important;
}

.view-mode-group :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: var(--accent-blue) !important;
  border-color: var(--accent-blue) !important;
  color: #ffffff !important;
  box-shadow: var(--ui-control-shadow) !important;
}

/* Filters and Chips */
.filters-chips-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--border-subtle);
  padding-bottom: 12px;
  flex-wrap: wrap;
}

.chips-list {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-chip {
  height: 32px;
  padding: 0 14px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel-raised);
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
}

.filter-chip:hover {
  border-color: var(--accent-blue);
  color: var(--accent-blue);
}

.filter-chip.active {
  background: var(--accent-blue);
  border-color: var(--accent-blue);
  color: #ffffff;
}

.chip-count {
  font-size: 11px;
  font-weight: 700;
  background: rgba(0, 0, 0, 0.15);
  padding: 1px 6px;
  border-radius: 99px;
}

.filter-chip.active .chip-count {
  background: rgba(255, 255, 255, 0.25);
  color: #ffffff;
}

.checkbox-filters {
  display: flex;
  align-items: center;
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

.apps-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  grid-auto-rows: 80px;
  gap: 12px;
}

.app-tile {
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel);
  border-radius: var(--ui-radius-lg);
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  cursor: pointer;
  position: relative;
  transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}

.app-tile:hover {
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
  gap: 6px;
  overflow: visible;
}

.meta-text {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}

.divider-dot {
  color: var(--text-muted);
  font-weight: bold;
}

.dot-state {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  margin-left: 2px;
  margin-right: 2px;
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

.app-status-badge {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.mini-update-badge {
  transform: scale(0.85);
  transform-origin: center;
}

/* Custom Context Menu */
.custom-context-menu {
  position: fixed;
  z-index: 3000;
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  box-shadow: var(--ui-control-shadow);
  padding: 4px;
  min-width: 160px;
}

.context-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.context-item:hover:not(.disabled) {
  background: var(--ui-control-hover-bg);
  color: var(--text-primary);
}

.context-item.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Dialog and Profiles form */
.profile-edit-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.profile-form {
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 16px;
}

.profile-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.profile-form-grid .full-width {
  grid-column: span 2;
}

.local-picker-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
}

.uploader {
  flex-shrink: 0;
}

.profile-add-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 12px;
}

.mini-profile-icon {
  width: 24px;
  height: 24px;
  border-radius: 4px;
  background: var(--surface-panel-raised);
}

.pattern-code {
  background: var(--surface-panel-raised);
  border: 1px solid var(--border-subtle);
  border-radius: 4px;
  padding: 2px 6px;
  font-family: var(--font-mono);
  color: var(--accent-blue);
}

.mb-4 {
  margin-bottom: 16px;
}

.mr-1 {
  margin-right: 4px;
}

.mr-2 {
  margin-right: 8px;
}

.my-1 {
  margin-top: 4px;
  margin-bottom: 4px;
}

.flex-1 {
  flex: 1;
}

@media (max-width: 768px) {
  .apps-grid {
    grid-template-columns: 1fr;
  }
  .ui-page-header {
    flex-direction: column;
    align-items: flex-start;
  }
  .header-right {
    width: 100%;
    justify-content: space-between;
  }
  .search-input {
    flex: 1;
  }
  .profile-form-grid {
    grid-template-columns: 1fr;
  }
  .profile-form-grid .full-width {
    grid-column: span 1;
  }
}
</style>
