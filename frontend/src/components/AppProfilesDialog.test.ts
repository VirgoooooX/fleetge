// @vitest-environment happy-dom
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { i18n } from "@/i18n";
import AppProfilesDialog from "./AppProfilesDialog.vue";

const store = vi.hoisted(() => ({
  fetchAppProfiles: vi.fn(),
  saveAppProfiles: vi.fn(),
  savingAppProfiles: new Set<string>(),
}));
vi.mock("@/stores/settings", () => ({ useSettingsStore: () => store }));

const entry = (pattern: string, icon: string | null = null) => ({
  stack_pattern: pattern, title: null, app_url: null, group: null, icon_value: icon,
});

let wrapper: VueWrapper;

beforeEach(() => {
  vi.resetAllMocks();
  i18n.global.locale.value = "en-US";
  store.saveAppProfiles.mockResolvedValue(undefined);
});
afterEach(() => wrapper?.unmount());

async function render(profiles = [entry("old")]) {
  store.fetchAppProfiles.mockResolvedValue({ profiles, available_files: [] });
  wrapper = mount(AppProfilesDialog, {
    props: { hostId: "host-a", hostName: "Host A", modelValue: true },
    attachTo: document.body,
    global: {
      plugins: [i18n],
      stubs: { teleport: true },
    },
  });
  await flushPromises();
}

const patternInput = () => wrapper.get('input[placeholder="e.g. rsshub or app* or *db"]');
const apply = async () => {
  await wrapper.get(".form-actions button:last-child").trigger("click");
  await flushPromises();
};
const save = async () => {
  await wrapper.get(".dialog-actions-row button:last-child").trigger("click");
  await flushPromises();
};
const edit = (pattern: string) => wrapper.get(`button[aria-label="Edit ${pattern}"]`).trigger("click");

async function expectSaved(profiles: ReturnType<typeof entry>[]) {
  await save();
  expect(store.saveAppProfiles).toHaveBeenLastCalledWith("host-a", profiles);
}

describe("App profiles editor", () => {
  it("replaces the original entry when its pattern changes", async () => {
    await render();
    await edit("old");
    await patternInput().setValue("new");
    await apply();
    expect(patternInput().element).toHaveProperty("value", "");
    await expectSaved([entry("new")]);
  });

  it.each([["first", "second"], ["second", "first"]])("merges %s into the existing %s entry", async (source, target) => {
    await render([entry("first"), entry("second")]);
    await edit(source);
    await patternInput().setValue(target);
    await wrapper.get('input[placeholder="e.g. RSSHub"]').setValue("updated");
    await apply();
    await save();
    expect(store.saveAppProfiles).toHaveBeenLastCalledWith("host-a", [{ ...entry(target), title: "updated" }]);
  });

  it("preserves an absolute icon path on edit", async () => {
    const profile = entry("app", "/api/static/icons/app.svg");
    await render([profile]);
    await edit("app");
    await apply();
    await expectSaved([profile]);
  });

  it("continues editing the selected entry after an earlier row is removed", async () => {
    await render([entry("first"), entry("second")]);
    await edit("second");
    await wrapper.get('button[aria-label="Remove first"]').trigger("click");
    await patternInput().setValue("renamed");
    await apply();
    await expectSaved([entry("renamed")]);
  });

  it("leaves entries unchanged when form validation fails", async () => {
    await render();
    await patternInput().setValue("new");
    await wrapper.get('input[placeholder="e.g. http://192.168.1.100:1200"]').setValue("invalid-url");
    await apply();
    await expectSaved([entry("old")]);
  });

  it("emits close and refresh only after persistence succeeds", async () => {
    await render();
    store.saveAppProfiles.mockRejectedValueOnce(new Error("save failed"));
    await save();
    expect(wrapper.emitted("update:modelValue")).toBeUndefined();
    expect(wrapper.emitted("saved")).toBeUndefined();
    await expectSaved([entry("old")]);
    expect(wrapper.emitted("update:modelValue")).toEqual([[false]]);
    expect(wrapper.emitted("saved")).toEqual([[]]);
  });
});
