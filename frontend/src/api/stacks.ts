import { isAxiosError } from "axios";
import { apiClient } from "./client";
import { apiErrorDetail } from "./errors";

interface ComposeDetail {
  compose_yaml: string;
  compose_env: string;
  compose_file_name: string;
  is_managed_by_agent: boolean;
}

export interface ComposeDeployPayload {
  stackName: string;
  composeYaml: string;
  composeEnv: string;
  composeFileName: string;
  isAdd: boolean;
}

export interface AutoUpdateState {
  enabled: boolean;
  reason: string;
  unavailable_reason: string;
}


export function stackPath(hostId: string, stackName: string) {
  return `/api/hosts/${encodeURIComponent(hostId)}/stacks/${encodeURIComponent(stackName)}`;
}

export function composeRequestBody(payload: ComposeDeployPayload) {
  return {
    compose_yaml: payload.composeYaml,
    compose_env: payload.composeEnv,
    compose_file_name: payload.composeFileName,
    is_add: payload.isAdd,
  };
}

export function fetchStackCompose(hostId: string, stackName: string, signal?: AbortSignal) {
  return apiClient.get<ComposeDetail>(`${stackPath(hostId, stackName)}/compose`, { signal });
}

export function saveStackCompose(hostId: string, payload: ComposeDeployPayload) {
  return apiClient.put<{ success: boolean; message: string; log_tail?: string | null }>(
    `${stackPath(hostId, payload.stackName)}/compose`,
    composeRequestBody(payload),
    { timeout: 60000 },
  );
}

export function fetchStackAutoUpdate(hostId: string, stackName: string, signal?: AbortSignal) {
  return apiClient.get<AutoUpdateState>(`${stackPath(hostId, stackName)}/auto-update`, { signal });
}

export function saveStackAutoUpdate(hostId: string, stackName: string, enabled: boolean) {
  return apiClient.put<Pick<AutoUpdateState, "enabled" | "reason">>(
    `${stackPath(hostId, stackName)}/auto-update`,
    { enabled },
  );
}

export function stackRequestError(error: unknown) {
  const data = isAxiosError<{ log_tail?: string }>(error)
    ? error.response?.data
    : undefined;
  const detail = apiErrorDetail(error);
  return { detail: detail || (error instanceof Error ? error.message : ""), logTail: data?.log_tail };
}
