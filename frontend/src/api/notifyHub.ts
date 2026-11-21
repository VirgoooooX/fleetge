import { apiClient } from "./client";

export interface NotifyHubSettings {
  url: string;
  recipient: string;
  key_configured: boolean;
}

type NotifyHubUpdate = Pick<NotifyHubSettings, "url" | "recipient"> & {
  api_key: string | null;
};

const notifyHubPath = "/api/admin/notifyhub";
const billingAlertsPath = "/api/admin/billing-alerts";

export const notifyHubApi = {
  async getSettings(signal?: AbortSignal): Promise<NotifyHubSettings> {
    const { data } = await apiClient.get<NotifyHubSettings>(notifyHubPath, { signal });
    return data;
  },
  async saveSettings(update: NotifyHubUpdate): Promise<NotifyHubSettings> {
    const { data } = await apiClient.put<NotifyHubSettings>(notifyHubPath, update);
    return data;
  },
  async getBillingAlerts(signal?: AbortSignal): Promise<boolean> {
    const { data } = await apiClient.get<{ enabled: boolean }>(billingAlertsPath, { signal });
    return data.enabled ?? true;
  },
  async saveBillingAlerts(enabled: boolean): Promise<boolean> {
    const { data } = await apiClient.put<{ enabled: boolean }>(billingAlertsPath, { enabled });
    return data.enabled;
  },
};
