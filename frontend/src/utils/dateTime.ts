export function parseApiTimestamp(value: string): number {
  const trimmed = String(value || "").trim().replace(" ", "T");
  if (!trimmed) return Number.NaN;
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(trimmed) ? trimmed : `${trimmed}Z`;
  return Date.parse(normalized);
}

export function remainingInviteSeconds(expiresAt: string, now = Date.now()): number {
  const expiresAtMs = parseApiTimestamp(expiresAt);
  if (!Number.isFinite(expiresAtMs)) return 0;
  return Math.max(0, Math.ceil((expiresAtMs - now) / 1000));
}
