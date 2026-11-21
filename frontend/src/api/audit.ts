import { apiClient } from "./client";

export interface AuditEntry {
  id: number;
  timestamp: string;
  user: string;
  action: string;
  host_id: string;
  stack_name?: string | null;
  result: string;
  detail?: string | null;
  ip_address?: string | null;
}

export async function fetchAuditLogs(params: { limit: number; offset: number }) {
  const { data } = await apiClient.get<AuditEntry[]>("/api/audit-logs", { params });
  return data ?? [];
}
