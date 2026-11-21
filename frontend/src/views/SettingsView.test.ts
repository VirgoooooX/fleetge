// @vitest-environment happy-dom
import { mount, flushPromises, type VueWrapper } from "@vue/test-utils";
import { createPinia } from "pinia";
import { createI18n } from "vue-i18n";
import { createMemoryHistory, createRouter } from "vue-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { HostConfigResponse } from "@/api/settings";
import { settingsApi } from "@/api/settings";
import { useSettingsStore } from "@/stores/settings";
import HostsSettingsSection from "@/components/settings/HostsSettingsSection.vue";

vi.mock("@/stores/dashboard", () => ({ useDashboardStore: () => ({ fetchHosts: vi.fn() }) }));

function deferred<T>() {
  let resolve!: (data: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

const host = (hostId: string): HostConfigResponse => ({
  host_id: hostId, agent_url: `http://${hostId}`, display_name: hostId.toUpperCase(),
  sort_order: 10, traffic_billing_day: 1, enabled: true, has_agent_token: true,
  location_confirmed: false,
});
const subscription = (provider: string) => ({
  provider, plan_name: null, payment_amount: null, currency: "CNY", payment_cycle: null,
  next_payment_date: null, service_expiry_date: null, auto_renew: false,
  management_url: null, notes: null, quota_enabled: false, traffic_quota_value: null,
  traffic_quota_unit: "GiB", traffic_direction: "both", billing_timezone: "Asia/Shanghai",
  alerts_enabled: true,
});
const edit = (id: string) => ({ section: "hosts", action: "edit-host", host: id });
let wrapper: VueWrapper;

async function openHosts(query = { section: "hosts" }) {
  const pinia = createPinia();
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/settings", name: "settings", component: HostsSettingsSection }],
  });
  await router.push({ name: "settings", query });
  const i18n = createI18n({
    legacy: false, locale: "en-US", missingWarn: false, fallbackWarn: false,
    messages: { "en-US": { "compose.saveAction": "Save", "compose.cancel": "Cancel" } },
  });
  wrapper = mount(HostsSettingsSection, {
    props: { active: true },
    attachTo: document.body,
    global: { plugins: [pinia, router, i18n], stubs: { teleport: true, ElSelect: true, ElOption: true } },
  });
  await flushPromises();
  return { router, store: useSettingsStore(pinia) };
}

function dialogButton(label: string) {
  const button = wrapper.findAll(".host-editor-dialog button").find((button) => button.text().trim() === label);
  if (!button) throw new Error(`Host editor button ${label} not found`);
  return button;
}

function dialogInputs() {
  return wrapper.findAll<HTMLInputElement>(".host-editor-dialog input").map((input) => input.element.value);
}

beforeEach(() => {
  vi.spyOn(settingsApi, "fetchHosts").mockResolvedValue([host("a"), host("b")]);
  vi.spyOn(settingsApi, "fetchSubscription").mockImplementation(async (id) => subscription(`provider-${id}`));
  vi.spyOn(settingsApi, "updateHost").mockImplementation(async (id) => host(id));
  vi.spyOn(settingsApi, "saveSubscription").mockResolvedValue(undefined);
});

afterEach(() => {
  wrapper?.unmount();
  vi.restoreAllMocks();
});

describe("Host editing isolation", () => {
  it("opens the requested host after the host list arrives and consumes the route action once", async () => {
    const list = deferred<HostConfigResponse[]>();
    vi.mocked(settingsApi.fetchHosts).mockReturnValueOnce(list.promise);
    const { router, store } = await openHosts(edit("b"));
    expect(settingsApi.fetchSubscription).not.toHaveBeenCalled();
    expect(router.currentRoute.value.query).toEqual(edit("b"));
    list.resolve([host("a"), host("b")]);
    await flushPromises();
    expect(settingsApi.fetchSubscription).toHaveBeenCalledExactlyOnceWith("b");
    expect(dialogInputs()).toContain("provider-b");
    expect(router.currentRoute.value.query).toEqual({ section: "hosts" });
    await store.fetchHosts();
    await flushPromises();
    expect(settingsApi.fetchSubscription).toHaveBeenCalledTimes(1);
  });

  it("ignores the previous host's late response after opening a different editor", async () => {
    const first = deferred<ReturnType<typeof subscription>>();
    vi.mocked(settingsApi.fetchSubscription).mockReturnValueOnce(first.promise);
    const { router } = await openHosts(edit("a"));
    await router.replace({ name: "settings", query: edit("b") });
    await flushPromises();
    expect(dialogInputs()).toContain("provider-b");
    first.resolve(subscription("provider-a"));
    await flushPromises();
    expect(dialogInputs()).toContain("provider-b");
    expect(dialogInputs()).not.toContain("provider-a");
  });

  it("does not enable save when the previous host's request fails while the new host is loading", async () => {
    const first = deferred<ReturnType<typeof subscription>>();
    const second = deferred<ReturnType<typeof subscription>>();
    vi.mocked(settingsApi.fetchSubscription).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { router } = await openHosts(edit("a"));
    await router.replace({ name: "settings", query: edit("b") });
    first.reject(new Error("old request failed"));
    await flushPromises();
    expect(dialogButton("Save").attributes("disabled")).toBeDefined();
    second.resolve(subscription("provider-b"));
    await flushPromises();
    expect(dialogButton("Save").attributes("disabled")).toBeUndefined();
  });

  it("clears a typed token when switching hosts and saves the new host with its token untouched", async () => {
    const { router } = await openHosts(edit("a"));
    await wrapper.get(".host-editor-dialog input[type=password]").setValue("my-previous-token");
    await router.replace({ name: "settings", query: edit("b") });
    await flushPromises();
    expect(dialogInputs()).not.toContain("my-previous-token");
    await dialogButton("Save").trigger("click");
    await flushPromises();
    expect(settingsApi.updateHost).toHaveBeenCalledWith("b", expect.objectContaining({ agent_token: null }));
  });

  it("saves the original subscription if the user opens another host before the save completes", async () => {
    const update = deferred<HostConfigResponse>();
    vi.mocked(settingsApi.updateHost).mockReturnValueOnce(update.promise);
    const { router } = await openHosts(edit("a"));
    await dialogButton("Save").trigger("click");
    await flushPromises();
    expect(settingsApi.updateHost).toHaveBeenCalledWith("a", expect.anything());
    await router.replace({ name: "settings", query: edit("b") });
    await flushPromises();
    update.resolve(host("a"));
    await flushPromises();
    expect(settingsApi.saveSubscription).toHaveBeenCalledWith("a", expect.objectContaining({ provider: "provider-a" }));
    expect(dialogInputs()).toContain("provider-b");
  });
});
