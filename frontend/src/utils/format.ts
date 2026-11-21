import { i18n, t } from "@/i18n";

const paymentCycles = {
  monthly: "billing.cycle.monthly",
  quarterly: "billing.cycle.quarterly",
  semiannual: "billing.cycle.semiannual",
  annual: "billing.cycle.annual",
  once: "billing.cycle.once",
} as const;

export function formatExpiry(days?: number | null): string {
  if (days == null || !Number.isFinite(days)) return "";
  if (days < 0) return t("billing.expired", { days: Math.abs(days) });
  if (days === 0) return t("billing.dueToday");
  return t("billing.dueIn", { days });
}

export function formatSubscriptionPrice(
  amount?: number | null,
  currency = "CNY",
  cycle: string | null = "annual",
  { fixedDecimals = false } = {},
): string {
  if (amount == null || !Number.isFinite(amount)) return "";
  const label = cycle && Object.prototype.hasOwnProperty.call(paymentCycles, cycle)
    ? paymentCycles[cycle as keyof typeof paymentCycles]
    : paymentCycles.annual;
  const code = /^[A-Z]{3}$/.test(currency) ? currency : "CNY";
  const price = new Intl.NumberFormat(i18n.global.locale.value, {
    style: "currency",
    currency: code,
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: fixedDecimals ? 2 : 0,
    maximumFractionDigits: 2,
  }).format(amount);
  return `${price} / ${t(label)}`;
}

export function formatBillingReset(nextResetAt?: string | null, billingDay?: number, timeZone?: string): string {
  const date = nextResetAt ? new Date(nextResetAt) : undefined;
  if (date && Number.isFinite(date.getTime())) {
    try {
      const label = new Intl.DateTimeFormat(i18n.global.locale.value, {
        month: "short",
        day: "numeric",
        timeZone,
      }).format(date);
      return t("billing.resetDate", { date: label });
    } catch (error) {
      if (!(error instanceof RangeError)) throw error;
    }
  }
  return t("billing.resetDay", { day: billingDay || 1 });
}
