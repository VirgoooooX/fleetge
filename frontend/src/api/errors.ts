import { isAxiosError } from "axios";

export function apiErrorDetail(error: unknown): string | undefined {
  const detail = isAxiosError<{ detail?: unknown }>(error)
    ? error.response?.data?.detail
    : undefined;
  return typeof detail === "string" && detail.trim() ? detail : undefined;
}

export function apiErrorMessage(error: unknown, fallback: string): string {
  return apiErrorDetail(error) || (typeof error === "string" && error.trim() ? error : fallback);
}
