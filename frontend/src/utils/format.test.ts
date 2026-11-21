import { beforeEach, describe, expect, it } from "vitest";
import { i18n } from "@/i18n";
import { formatBillingReset, formatExpiry, formatSubscriptionPrice } from "./format";
import { formatBytes, splitBytes, splitRate } from "./formatBytes";

describe("format utilities", () => {
  beforeEach(() => {
    i18n.global.locale.value = "zh-CN";
  });

  it("formats expiry countdowns in both locales", () => {
    expect(formatExpiry(null)).toBe("");
    expect(formatExpiry(-3)).toBe("已逾期 3 天");
    expect(formatExpiry(0)).toBe("今日到期");
    expect(formatExpiry(12)).toBe("12 天后到期");

    i18n.global.locale.value = "en-US";
    expect(formatExpiry(-3)).toBe("3 days overdue");
    expect(formatExpiry(0)).toBe("Expires today");
    expect(formatExpiry(12)).toBe("Expires in 12 days");
  });

  it("formats subscription prices with compact and fixed decimals", () => {
    expect(formatSubscriptionPrice(undefined)).toBe("");
    expect(formatSubscriptionPrice(52, "CNY", "annual")).toBe("¥52 / 年");
    expect(formatSubscriptionPrice(49.9, "USD", "monthly")).toBe("$49.9 / 月");
    expect(formatSubscriptionPrice(52, "CNY", "annual", { fixedDecimals: true })).toBe("¥52.00 / 年");

    i18n.global.locale.value = "en-US";
    expect(formatSubscriptionPrice(19.99, "EUR", "quarterly")).toBe("€19.99 / quarter");
  });

  it("formats billing reset dates with timezone fallback to billing day", () => {
    expect(formatBillingReset(null, 15)).toBe("每月 15 日重置");
    expect(formatBillingReset("2026-04-01T00:00:00Z", 1, "UTC")).toContain("重置");

    i18n.global.locale.value = "en-US";
    expect(formatBillingReset(undefined, 8)).toBe("Resets on day 8 of each month");
    expect(formatBillingReset("2026-04-01T00:00:00Z", 1, "Invalid/Timezone")).toBe(
      "Resets on day 1 of each month",
    );
  });

  it("splits and formats byte volumes and transfer rates", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(splitBytes(10 * 1024 * 1024)).toEqual({ val: "10", unit: "MB" });
    expect(splitRate(-2048)).toEqual({ val: "2.0", unit: "KB/s" });
  });
});
