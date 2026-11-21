import { isAxiosError } from "axios";
import { apiClient } from "./client";

export interface FleetLocation {
  latitude: number;
  longitude: number;
  city?: string | null;
  region?: string | null;
  country?: string | null;
  country_code?: string | null;
  source?: string | null;
  confirmed: boolean;
  confidence?: string | null;
}

export interface NetworkIdentityEvidence {
  observedAt?: string;
  effectiveIp?: string | null;
  effectiveSource?: string | null;
  confidence?: string;
  conflict?: boolean;
  locationDrift?: boolean;
  fixedOverride?: string | null;
  categories?: Record<string, {
    status?: string;
    addresses?: string[];
    eligibleAddresses?: string[];
    eligible?: boolean;
    mode?: string;
    excludedReason?: string | null;
    excludedReasons?: string[];
    cnameChain?: string[];
  }>;
}

export interface FleetLocationSearchResult extends FleetLocation {
  name: string;
}

export interface FleetMapStackService {
  name: string;
  container_id?: string;
  state: string;
  status: string;
  health?: Record<string, unknown> | null;
}

export interface FleetMapStack {
  name: string;
  status: string;
  service_count: number;
  running_count: number;
  services: FleetMapStackService[];
}

export interface FleetMapHost {
  host_id: string;
  display_name: string;
  enabled: boolean;
  status: "online" | "degraded" | "offline" | "unknown";
  metrics?: Record<string, unknown> | null;
  container_count: number;
  last_seen?: string | null;
  error_message?: string | null;
  agent_instance_id?: string | null;
  location?: FleetLocation | null;
  network_identity?: NetworkIdentityEvidence | null;
  stacks: FleetMapStack[];
}

export interface FleetMapCenter {
  name: string;
  city?: string | null;
  region?: string | null;
  country?: string | null;
  country_code?: string | null;
  latitude: number;
  longitude: number;
  confirmed: boolean;
}

export interface FleetMapSnapshot {
  center: FleetMapCenter;
  hosts: FleetMapHost[];
  counts: { total: number; online: number; degraded: number; offline: number; unlocated: number };
  updated_at: string;
}

const settingsUrl = "/api/admin/fleet-map/settings";
const adminHostUrl = (hostId: string) => `/api/admin/hosts/${encodeURIComponent(hostId)}`;

export function fleetRequestError(error: unknown, includeMessage = false) {
  if (isAxiosError<{ detail?: unknown }>(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string" && detail) return detail;
  }
  return includeMessage && error instanceof Error ? error.message : "";
}

export async function getFleetSnapshot(signal: AbortSignal) {
  const response = await apiClient.get<FleetMapSnapshot>("/api/fleet-map", { signal });
  return response.data;
}

export async function getFleetCenterSettings() {
  const response = await apiClient.get<FleetMapCenter>(settingsUrl);
  return response.data;
}

export async function suggestFleetCenterLocation() {
  const response = await apiClient.post<FleetLocation>(`${settingsUrl}/suggest`);
  return response.data;
}

export async function updateFleetCenter(data: FleetMapCenter) {
  const response = await apiClient.put<FleetMapCenter>(settingsUrl, data);
  return response.data;
}

export async function updateFleetHostLocation(hostId: string, location: FleetLocation) {
  const response = await apiClient.put<{ location: FleetLocation }>(`${adminHostUrl(hostId)}/location`, location);
  return response.data.location;
}

export async function suggestFleetHostLocation(hostId: string) {
  const response = await apiClient.post<{ location: FleetLocation }>(`${adminHostUrl(hostId)}/location/suggest`);
  return response.data.location;
}

export async function refreshFleetNetworkIdentity(hostId: string, force: boolean, signal?: AbortSignal) {
  const response = await apiClient.post<NetworkIdentityEvidence>(
    `${adminHostUrl(hostId)}/network-identity/refresh`,
    undefined,
    { params: { force }, signal },
  );
  return response.data;
}

export async function updateFleetNetworkIdentityOverride(hostId: string, ip: string | null) {
  const response = await apiClient.put<NetworkIdentityEvidence>(`${adminHostUrl(hostId)}/network-identity/override`, { ip });
  return response.data;
}

export async function searchFleetLocations(query: string, language = "zh", signal?: AbortSignal) {
  const response = await apiClient.get<{ results?: FleetLocationSearchResult[] }>("/api/admin/location/search", {
    params: { q: query, language },
    signal,
  });
  return response.data.results ?? [];
}
