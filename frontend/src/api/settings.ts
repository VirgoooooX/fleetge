import { apiClient } from "./client";

export interface SettingItem {
  key: string;
  value: string;
  type: "number" | "string" | "password";
  is_writable: boolean;
  description: string;
  min_value?: number | null;
  max_value?: number | null;
  unit?: string | null;
}

export interface HostConfigResponse {
  host_id: string;
  display_name: string;
  enabled: boolean;
  sort_order: number;
  traffic_billing_day: number;
  logo?: string | null;
  agent_url?: string | null;
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

export interface HostUpdateRequest {
  display_name: string;
  enabled?: boolean;
  sort_order?: number;
  traffic_billing_day?: number | null;
  logo?: string | null;
  agent_url?: string | null;
  agent_token?: string | null;
}

export interface HostCreateRequest extends HostUpdateRequest {
  host_id: string;
  traffic_billing_day?: number;
}

export type PaymentCycle = "monthly" | "quarterly" | "semiannual" | "annual" | "once";

export interface HostSubscription {
  provider: string | null;
  plan_name: string | null;
  payment_amount: number | null;
  currency: string;
  payment_cycle: PaymentCycle | null;
  next_payment_date: string | null;
  service_expiry_date: string | null;
  auto_renew: boolean;
  management_url: string | null;
  notes: string | null;
  quota_enabled: boolean;
  traffic_quota_value: number | null;
  traffic_quota_unit: string;
  traffic_direction: string;
  billing_timezone: string;
  alerts_enabled: boolean;
}

export type EnrollmentStatus =
  | "issued" | "downloaded" | "verifying" | "active" | "needs_url"
  | "failed" | "expired" | "revoked";

export interface EnrollmentInvite {
  invite_id: string;
  status: EnrollmentStatus;
  expires_at: string;
  downloaded_at?: string | null;
  completed_at?: string | null;
  host_id?: string | null;
  agent_instance_id: string;
  agent_port: number;
  stack_root: string;
  agent_image: string;
  agent_public_host: string;
  agent_public_url: string;
  failure_reason?: string | null;
  install_command?: string | null;
}

export interface EnrollmentInviteRequest {
  dashboard_url: string;
  agent_public_host: string;
  stack_root: string;
  agent_port: number;
  agent_image?: string;
}

interface EnrollmentRetryResponse {
  status: EnrollmentStatus;
  agent_public_url?: string | null;
  message?: string | null;
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

const hostsPath = "/api/admin/hosts";
const settingsPath = "/api/admin/settings";
const invitesPath = "/api/admin/enrollment-invites";
const hostPath = (hostId: string) => `${hostsPath}/${encodeURIComponent(hostId)}`;
const subscriptionPath = (hostId: string) => `/api/hosts/${encodeURIComponent(hostId)}/subscription`;
const invitePath = (inviteId: string) => `${invitesPath}/${encodeURIComponent(inviteId)}`;

export const settingsApi = {
  async fetchSettings() {
    const { data } = await apiClient.get<{ settings: SettingItem[] }>(settingsPath);
    return data.settings ?? [];
  },
  async saveSettings(updates: Record<string, string>) {
    const { data } = await apiClient.put<{ settings: SettingItem[] }>(settingsPath, { settings: updates });
    return data.settings ?? [];
  },
  async fetchHosts() {
    const { data } = await apiClient.get<HostConfigResponse[]>(hostsPath);
    return data ?? [];
  },
  async createHost(request: HostCreateRequest) {
    const { data } = await apiClient.post<HostConfigResponse>(hostsPath, request);
    return data;
  },
  async updateHost(hostId: string, request: HostUpdateRequest) {
    const { data } = await apiClient.put<HostConfigResponse>(hostPath(hostId), request);
    return data;
  },
  async deleteHost(hostId: string) {
    await apiClient.delete(hostPath(hostId));
  },
  async testConnection(hostId: string) {
    const { data } = await apiClient.post<ConnectionTestResponse>(`${hostPath(hostId)}/test-connection`);
    return data;
  },
  async testNewConnection(request: HostCreateRequest) {
    const { data } = await apiClient.post<ConnectionTestResponse>(`${hostsPath}/test-connection`, request);
    return data;
  },
  async fetchSubscription(hostId: string) {
    const { data } = await apiClient.get<HostSubscription>(subscriptionPath(hostId));
    return data;
  },
  async saveSubscription(hostId: string, request: HostSubscription) {
    await apiClient.put(subscriptionPath(hostId), request);
  },
  async fetchStackIcons(hostId: string) {
    const { data } = await apiClient.get<{ icons: StackIconEntry[]; available_files: string[] }>(`${hostPath(hostId)}/stack-icons`);
    return data;
  },
  async saveStackIcons(hostId: string, icons: StackIconEntry[]) {
    await apiClient.put(`${hostPath(hostId)}/stack-icons`, { icons });
  },
  async uploadIcon(hostId: string, file: File) {
    const form = new FormData();
    form.append("file", file);
    const { data } = await apiClient.post<{ filename: string }>(`${hostPath(hostId)}/stack-icons/upload`, form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return data.filename;
  },
  async fetchGlobalEnv(hostId: string) {
    const { data } = await apiClient.get<{ content: string }>(`${hostPath(hostId)}/global-env`);
    return data.content ?? "";
  },
  async saveGlobalEnv(hostId: string, content: string) {
    await apiClient.put(`${hostPath(hostId)}/global-env`, { content });
  },
  async fetchAppProfiles(hostId: string) {
    const { data } = await apiClient.get<{ profiles: AppProfileEntry[]; available_files: string[] }>(`${hostPath(hostId)}/app-profiles`);
    return data;
  },
  async saveAppProfiles(hostId: string, profiles: AppProfileEntry[]) {
    await apiClient.put(`${hostPath(hostId)}/app-profiles`, { profiles });
  },
  async fetchEnrollmentInvites(signal?: AbortSignal) {
    const { data } = await apiClient.get<EnrollmentInvite[]>(invitesPath, { signal });
    return data ?? [];
  },
  async createEnrollmentInvite(request: EnrollmentInviteRequest) {
    const { data } = await apiClient.post<EnrollmentInvite>(invitesPath, request);
    return data;
  },
  async revokeEnrollmentInvite(inviteId: string) {
    const { data } = await apiClient.delete<EnrollmentInvite>(invitePath(inviteId));
    return data;
  },
  async retryEnrollmentInvite(inviteId: string) {
    const { data } = await apiClient.post<EnrollmentRetryResponse>(`${invitePath(inviteId)}/retry`, {});
    return data;
  },
};
