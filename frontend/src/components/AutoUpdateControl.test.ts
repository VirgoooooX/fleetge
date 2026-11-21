// @vitest-environment happy-dom
import { flushPromises, shallowMount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { i18n } from "@/i18n";
import { fetchStackAutoUpdate } from "@/api/stacks";
import AutoUpdateControl from "./AutoUpdateControl.vue";

vi.mock("@/api/stacks", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/api/stacks")>(),
  fetchStackAutoUpdate: vi.fn(),
}));

const state = (enabled: boolean) => ({ data: { enabled, reason: "", unavailable_reason: "" } });

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("auto-update control lifecycle", () => {
  it("discards an earlier host response after changing the target and stops polling when unmounted", async () => {
    vi.useFakeTimers();
    const pending = vi.mocked(fetchStackAutoUpdate);
    let resolveOld!: (response: ReturnType<typeof state>) => void;
    pending.mockReturnValueOnce(new Promise((resolve) => {
      resolveOld = (data) => resolve(data as Awaited<ReturnType<typeof fetchStackAutoUpdate>>);
    }));
    pending.mockResolvedValue(state(true) as Awaited<ReturnType<typeof fetchStackAutoUpdate>>);
    const wrapper = shallowMount(AutoUpdateControl, {
      props: { hostId: "old", stackName: "app" },
      global: { plugins: [i18n], renderStubDefaultSlot: true },
    });
    const originalSignal = pending.mock.calls[0][2];
    await wrapper.setProps({ hostId: "new" });
    resolveOld(state(false));
    await flushPromises();
    expect(originalSignal?.aborted).toBe(true);
    expect(wrapper.get("el-switch-stub").attributes("modelvalue")).toBe("true");
    expect(wrapper.emitted("refresh")).toBeUndefined();

    const hidden = vi.spyOn(document, "hidden", "get");
    hidden.mockReturnValue(true);
    await vi.advanceTimersByTimeAsync(15000);
    expect(pending).toHaveBeenCalledTimes(2);
    hidden.mockReturnValue(false);
    await vi.advanceTimersByTimeAsync(15000);
    expect(pending).toHaveBeenCalledTimes(3);
    wrapper.unmount();
    await vi.advanceTimersByTimeAsync(15000);
    expect(pending).toHaveBeenCalledTimes(3);
  });
});
