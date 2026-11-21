import { apiClient } from "./client";

export interface LauncherApp {
  host_id: string;
  host_name: string;
  host_status: string;
  stack_name: string;
  status: string;
  service_count: number;
  running_count: number;
  management_status: string;
  title: string | null;
  app_url: string | null;
  group: string | null;
  icon_url: string | null;
  update_status: string;
}

export async function listApps(signal: AbortSignal) {
  const { data } = await apiClient.get<LauncherApp[]>("/api/apps", { signal });
  return data ?? [];
}

export function isRunning(status: string) {
  return status === "running" || status === "active";
}
