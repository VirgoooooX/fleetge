import type { ContainerStats, ContainerSummary, HostSummary, StackSummary, UpdateResult } from "@/stores/dashboard";
import { apiClient } from "./client";

interface HostDetailResponse {
  host: HostSummary;
  stacks: StackSummary[];
  containers: ContainerSummary[];
  container_stats: Record<string, ContainerStats>;
}

export function fetchHostDetail(hostId: string, refresh: boolean, signal: AbortSignal) {
  const path = `/api/hosts/${encodeURIComponent(hostId)}`;
  return refresh
    ? apiClient.post<HostDetailResponse>(`${path}/refresh`, undefined, { signal })
    : apiClient.get<HostDetailResponse>(path, { signal });
}

export function fetchUpdateResults(signal: AbortSignal) {
  return apiClient.get<UpdateResult[]>("/api/update-checks", { signal });
}
