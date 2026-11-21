import { defineStore } from "pinia";
import { reactive, ref } from "vue";
import {
  settingsApi,
  type AppProfileEntry,
  type ConnectionTestResponse,
  type HostConfigResponse,
  type HostCreateRequest,
  type HostUpdateRequest,
  type SettingItem,
} from "@/api/settings";
import { apiErrorMessage } from "@/api/errors";
import { useDashboardStore } from "./dashboard";

export type { AppProfileEntry, HostConfigResponse, SettingItem, StackIconEntry } from "@/api/settings";

function trackByHost<T>(pending: Set<string>, hostId: string, request: () => Promise<T>) {
  if (pending.has(hostId)) return Promise.reject(new Error("Host action is already in progress"));
  pending.add(hostId);
  return request().finally(() => pending.delete(hostId));
}

export const useSettingsStore = defineStore("settings", () => {
  const settings = ref<SettingItem[]>([]);
  const hosts = ref<HostConfigResponse[]>([]);
  const loadingSettings = ref(false);
  const savingSettings = ref(false);
  const loadingHosts = ref(false);
  const updatingHosts = reactive(new Set<string>());
  const deletingHosts = reactive(new Set<string>());
  const testingHosts = reactive(new Set<string>());
  const savingGlobalEnv = reactive(new Set<string>());
  const savingAppProfiles = reactive(new Set<string>());
  let settingsRevision = 0;
  let hostsRevision = 0;
  let hostListRequest = 0;

  async function fetchSettings() {
    const revision = settingsRevision;
    loadingSettings.value = true;
    try {
      const data = await settingsApi.fetchSettings();
      if (revision === settingsRevision) settings.value = data;
    } finally {
      loadingSettings.value = false;
    }
  }

  async function saveSettings(updates: Record<string, string>) {
    savingSettings.value = true;
    try {
      const data = await settingsApi.saveSettings(updates);
      ++settingsRevision;
      settings.value = data;
      void useDashboardStore().fetchHosts();
    } finally {
      savingSettings.value = false;
    }
  }

  async function fetchHosts() {
    const requestId = ++hostListRequest;
    const revision = hostsRevision;
    loadingHosts.value = true;
    try {
      const data = await settingsApi.fetchHosts();
      if (requestId === hostListRequest && revision === hostsRevision) hosts.value = data;
    } finally {
      if (requestId === hostListRequest) loadingHosts.value = false;
    }
  }

  function applyHost(host: HostConfigResponse) {
    ++hostsRevision;
    const index = hosts.value.findIndex((item) => item.host_id === host.host_id);
    if (index < 0) hosts.value.push(host);
    else hosts.value[index] = host;
    hosts.value = [...hosts.value].sort((a, b) => a.sort_order - b.sort_order);
    void useDashboardStore().fetchHosts();
  }

  function createHost(request: HostCreateRequest) {
    return trackByHost(updatingHosts, request.host_id, async () => {
      const host = await settingsApi.createHost(request);
      applyHost(host);
      return host;
    });
  }

  function updateHost(hostId: string, request: HostUpdateRequest) {
    return trackByHost(updatingHosts, hostId, async () => {
      const host = await settingsApi.updateHost(hostId, request);
      applyHost(host);
      return host;
    });
  }

  function deleteHost(hostId: string) {
    return trackByHost(deletingHosts, hostId, async () => {
      await settingsApi.deleteHost(hostId);
      ++hostsRevision;
      hosts.value = hosts.value.filter((host) => host.host_id !== hostId);
      void useDashboardStore().fetchHosts();
    });
  }

  async function testConnection(hostId: string): Promise<ConnectionTestResponse> {
    try {
      return await trackByHost(testingHosts, hostId, () => settingsApi.testConnection(hostId));
    } catch (error) {
      return { success: false, response_time_ms: 0, message: apiErrorMessage(error, "") };
    }
  }

  async function testNewConnection(request: HostCreateRequest): Promise<ConnectionTestResponse> {
    try {
      return await settingsApi.testNewConnection(request);
    } catch (error) {
      return { success: false, response_time_ms: 0, message: apiErrorMessage(error, "") };
    }
  }

  function saveGlobalEnv(hostId: string, content: string) {
    return trackByHost(savingGlobalEnv, hostId, () => settingsApi.saveGlobalEnv(hostId, content));
  }

  function saveAppProfiles(hostId: string, profiles: AppProfileEntry[]) {
    return trackByHost(savingAppProfiles, hostId, () => settingsApi.saveAppProfiles(hostId, profiles));
  }

  return {
    settings, hosts, loadingSettings, savingSettings, loadingHosts,
    updatingHosts, deletingHosts, testingHosts, savingGlobalEnv, savingAppProfiles,
    fetchSettings, saveSettings, fetchHosts, createHost, updateHost, deleteHost,
    testConnection, testNewConnection, saveGlobalEnv, saveAppProfiles,
    fetchStackIcons: settingsApi.fetchStackIcons,
    saveStackIcons: settingsApi.saveStackIcons,
    uploadIcon: settingsApi.uploadIcon,
    fetchGlobalEnv: settingsApi.fetchGlobalEnv,
    fetchAppProfiles: settingsApi.fetchAppProfiles,
  };
});
