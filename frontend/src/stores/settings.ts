import { defineStore } from "pinia";
import { ref } from "vue";
import { apiClient } from "@/api/client";

export interface SettingItem {
  key: string;
  value: string;
  type: "number" | "string" | "password";
  is_writable: boolean;
  description: string;
  min_value?: number;
  max_value?: number;
  unit?: string;
}

export interface HostConfigResponse {
  host_id: string;
  display_name: string;
  enabled: boolean;
  sort_order: number;
  traffic_billing_day: number;
  agent_url?: string;
  has_agent_token: boolean;
  agent_instance_id?: string;
  location_latitude?: number;
  location_longitude?: number;
  location_city?: string;
  location_region?: string;
  location_country?: string;
  location_country_code?: string;
  location_source?: string;
  location_confirmed: boolean;
  stack_icons?: Record<string, string>;
  app_profiles?: AppProfileEntry[];
}

export type EnrollmentStatus =
  | "issued" | "downloaded" | "verifying" | "active" | "needs_url"
  | "failed" | "expired" | "revoked";

export interface EnrollmentInvite {
  invite_id: string;
  status: EnrollmentStatus;
  expires_at: string;
  downloaded_at?: string;
  completed_at?: string;
  host_id?: string;
  agent_instance_id: string;
  agent_port: number;
  stack_root: string;
  agent_image: string;
  agent_public_host: string;
  agent_public_url: string;
  failure_reason?: string;
  install_command?: string;
}

export interface StackIconEntry {
  stack_pattern: string;
  icon_value: string;
}

export interface AppProfileEntry {
  stack_pattern: string;
  title: string | null;
  app_url: string | null;
  group: string | null;
  icon_value: string | null;
}

export interface ConnectionTestResponse {
  success: boolean;
  response_time_ms: number;
  message: string;
}

export const useSettingsStore = defineStore("settings", () => {
  const settings = ref<SettingItem[]>([]);
  const hosts = ref<HostConfigResponse[]>([]);
  const loading = ref(false);
  const saving = ref(false);
  const error = ref("");
  const enrollmentInvites = ref<EnrollmentInvite[]>([]);

  async function fetchSettings() {
    loading.value = true;
    error.value = "";
    try {
      const res = await apiClient.get("/api/admin/settings");
      settings.value = res.data.settings || [];
    } catch (e: any) {
      error.value = e.response?.data?.detail || e.message || "Failed to fetch settings";
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function saveSettings(updates: Record<string, string>) {
    saving.value = true;
    error.value = "";
    try {
      const res = await apiClient.put("/api/admin/settings", { settings: updates });
      settings.value = res.data.settings || [];
      
      // Proactively refresh dashboard store
      try {
        const { useDashboardStore } = await import("./dashboard");
        const dashboardStore = useDashboardStore();
        void dashboardStore.fetchHosts();
      } catch (err) {
        console.warn("Failed to trigger dashboard store refresh:", err);
      }
    } catch (e: any) {
      error.value = e.response?.data?.detail || e.message || "Failed to save settings";
      throw e;
    } finally {
      saving.value = false;
    }
  }

  async function fetchHosts() {
    loading.value = true;
    error.value = "";
    try {
      const res = await apiClient.get("/api/admin/hosts");
      hosts.value = res.data || [];
    } catch (e: any) {
      error.value = e.response?.data?.detail || e.message || "Failed to fetch hosts list";
      throw e;
    } finally {
      loading.value = false;
    }
  }

  async function createHost(data: any) {
    saving.value = true;
    try {
      const res = await apiClient.post("/api/admin/hosts", data);
      await fetchHosts();
      
      try {
        const { useDashboardStore } = await import("./dashboard");
        const dashboardStore = useDashboardStore();
        void dashboardStore.fetchHosts();
      } catch (err) {}
      
      return res.data;
    } catch (e: any) {
      throw e.response?.data?.detail || e.message || "Failed to create host";
    } finally {
      saving.value = false;
    }
  }

  async function updateHost(hostId: string, data: any) {
    saving.value = true;
    try {
      const res = await apiClient.put(`/api/admin/hosts/${hostId}`, data);
      await fetchHosts();
      
      try {
        const { useDashboardStore } = await import("./dashboard");
        const dashboardStore = useDashboardStore();
        void dashboardStore.fetchHosts();
      } catch (err) {}
      
      return res.data;
    } catch (e: any) {
      throw e.response?.data?.detail || e.message || "Failed to update host";
    } finally {
      saving.value = false;
    }
  }

  async function deleteHost(hostId: string) {
    saving.value = true;
    try {
      await apiClient.delete(`/api/admin/hosts/${hostId}`);
      await fetchHosts();
      
      try {
        const { useDashboardStore } = await import("./dashboard");
        const dashboardStore = useDashboardStore();
        void dashboardStore.fetchHosts();
      } catch (err) {}
    } catch (e: any) {
      throw e.response?.data?.detail || e.message || "Failed to delete host";
    } finally {
      saving.value = false;
    }
  }

  async function testConnection(hostId: string): Promise<ConnectionTestResponse> {
    try {
      const res = await apiClient.post(`/api/admin/hosts/${hostId}/test-connection`);
      return res.data;
    } catch (e: any) {
      return {
        success: false,
        response_time_ms: 0,
        message: e.response?.data?.detail || e.message || "Connection test failed",
      };
    }
  }

  async function testNewConnection(data: any): Promise<ConnectionTestResponse> {
    try {
      const res = await apiClient.post(`/api/admin/hosts/test-connection`, data);
      return res.data;
    } catch (e: any) {
      return {
        success: false,
        response_time_ms: 0,
        message: e.response?.data?.detail || e.message || "Connection test failed",
      };
    }
  }

  async function fetchStackIcons(hostId: string): Promise<{ icons: StackIconEntry[]; available_files: string[] }> {
    try {
      const res = await apiClient.get(`/api/admin/hosts/${hostId}/stack-icons`);
      return res.data;
    } catch (e: any) {
      throw e.response?.data?.detail || e.message || "Failed to fetch stack icons";
    }
  }

  async function saveStackIcons(hostId: string, icons: StackIconEntry[]) {
    saving.value = true;
    try {
      await apiClient.put(`/api/admin/hosts/${hostId}/stack-icons`, { icons });
    } catch (e: any) {
      throw e.response?.data?.detail || e.message || "Failed to save stack icons";
    } finally {
      saving.value = false;
    }
  }

  async function uploadIcon(hostId: string, file: File): Promise<string> {
    saving.value = true;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await apiClient.post(`/api/admin/hosts/${hostId}/stack-icons/upload`, formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });
      return res.data.filename;
    } catch (e: any) {
      throw e.response?.data?.detail || e.message || "Failed to upload stack icon";
    } finally {
      saving.value = false;
    }
  }

  async function fetchGlobalEnv(hostId: string): Promise<string> {
    try {
      const res = await apiClient.get(`/api/admin/hosts/${hostId}/global-env`);
      return res.data.content || "";
    } catch (e: any) {
      throw e.response?.data?.detail || e.message || "Failed to fetch global.env";
    }
  }

  async function saveGlobalEnv(hostId: string, content: string) {
    saving.value = true;
    try {
      await apiClient.put(`/api/admin/hosts/${hostId}/global-env`, { content });
    } catch (e: any) {
      throw e.response?.data?.detail || e.message || "Failed to save global.env";
    } finally {
      saving.value = false;
    }
  }

  async function fetchEnrollmentInvites() {
    const res = await apiClient.get("/api/admin/enrollment-invites");
    enrollmentInvites.value = res.data || [];
    return enrollmentInvites.value;
  }

  async function createEnrollmentInvite(data: {
    dashboard_url: string;
    agent_public_host: string;
    stack_root: string;
    agent_port: number;
    agent_image?: string;
  }): Promise<EnrollmentInvite> {
    const res = await apiClient.post("/api/admin/enrollment-invites", data);
    enrollmentInvites.value = [res.data, ...enrollmentInvites.value];
    return res.data;
  }

  async function revokeEnrollmentInvite(inviteId: string): Promise<EnrollmentInvite> {
    const res = await apiClient.delete(`/api/admin/enrollment-invites/${inviteId}`);
    await fetchEnrollmentInvites();
    return res.data;
  }

  async function retryEnrollmentInvite(inviteId: string) {
    const res = await apiClient.post(`/api/admin/enrollment-invites/${inviteId}/retry`, {});
    await Promise.all([fetchEnrollmentInvites(), fetchHosts()]);
    return res.data;
  }

  async function fetchAppProfiles(hostId: string): Promise<{ profiles: AppProfileEntry[]; available_files: string[] }> {
    try {
      const res = await apiClient.get(`/api/admin/hosts/${hostId}/app-profiles`);
      return res.data;
    } catch (e: any) {
      throw e.response?.data?.detail || e.message || "Failed to fetch app profiles";
    }
  }

  async function saveAppProfiles(hostId: string, profiles: AppProfileEntry[]) {
    saving.value = true;
    try {
      await apiClient.put(`/api/admin/hosts/${hostId}/app-profiles`, { profiles });
    } catch (e: any) {
      throw e.response?.data?.detail || e.message || "Failed to save app profiles";
    } finally {
      saving.value = false;
    }
  }

  return {
    settings,
    hosts,
    loading,
    saving,
    error,
    enrollmentInvites,
    fetchSettings,
    saveSettings,
    fetchHosts,
    createHost,
    updateHost,
    deleteHost,
    testConnection,
    testNewConnection,
    fetchStackIcons,
    saveStackIcons,
    fetchAppProfiles,
    saveAppProfiles,
    uploadIcon,
    fetchGlobalEnv,
    saveGlobalEnv,
    fetchEnrollmentInvites,
    createEnrollmentInvite,
    revokeEnrollmentInvite,
    retryEnrollmentInvite,
  };
});
