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
  agent_url?: string;
  has_agent_token: boolean;
  dockge_url?: string;
  dockge_username?: string;
  has_dockge_password: boolean;
  docker_proxy_url?: string;
  has_docker_proxy_auth: boolean;
  metrics_url?: string;
  has_metrics_auth: boolean;
  stack_icons?: Record<string, string>;
}

export interface StackIconEntry {
  stack_pattern: string;
  icon_value: string;
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

  return {
    settings,
    hosts,
    loading,
    saving,
    error,
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
    uploadIcon,
  };
});
