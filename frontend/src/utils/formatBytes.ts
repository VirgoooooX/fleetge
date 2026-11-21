const byteUnits = ["B", "KB", "MB", "GB", "TB"];
const rateUnits = ["B/s", "KB/s", "MB/s", "GB/s"];

function splitQuantity(value: number, units: readonly string[]) {
  if (!Number.isFinite(value) || value === 0) return { val: "0", unit: units[0] };
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index++;
  }
  return {
    val: value < 10 ? value.toFixed(1) : String(Math.round(value)),
    unit: units[index],
  };
}

export function splitBytes(bytes?: number | null) {
  return splitQuantity(bytes ?? 0, byteUnits);
}

export function splitRate(bytesPerSec?: number | null) {
  return splitQuantity(Math.abs(bytesPerSec ?? 0), rateUnits);
}

export function formatBytes(bytes?: number | null): string {
  const { val, unit } = splitBytes(bytes);
  return `${val} ${unit}`;
}
