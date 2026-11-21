/**
 * vue-i18n instance and helpers.
 *
 * Language preference is persisted to localStorage under "hd-locale".
 * Defaults to "zh-CN" (Chinese).
 */
import { createI18n } from "vue-i18n";
import zhCN from "./locales/zh-CN.json";
import enUS from "./locales/en-US.json";
import type { I18nSchema } from "./types";

export type Locale = "zh-CN" | "en-US";

const STORAGE_KEY = "hd-locale";

export function getStoredLocale(): Locale {
  const stored = typeof localStorage !== "undefined" ? localStorage.getItem(STORAGE_KEY) : null;
  if (stored === "zh-CN" || stored === "en-US") return stored;
  return "zh-CN";
}

export function setStoredLocale(locale: Locale): void {
  localStorage.setItem(STORAGE_KEY, locale);
}

export function getOppositeLocale(locale: Locale): Locale {
  return locale === "zh-CN" ? "en-US" : "zh-CN";
}

export const i18n = createI18n<[I18nSchema], Locale, false>({
  legacy: false,
  locale: getStoredLocale(),
  fallbackLocale: "zh-CN",
  messages: {
    "zh-CN": zhCN,
    "en-US": enUS,
  },
});

/** Type-safe translate function for use outside of components (stores, plain TS). */
export function t(key: keyof I18nSchema, params?: Record<string, unknown>): string {
  return params ? i18n.global.t(key, params) : i18n.global.t(key);
}
