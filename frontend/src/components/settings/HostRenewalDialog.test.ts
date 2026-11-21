// @vitest-environment happy-dom
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { i18n } from "@/i18n";
import HostRenewalDialog from "./HostRenewalDialog.vue";

const billingApiMock = vi.hoisted(() => ({
  getDates: vi.fn(),
  renew: vi.fn(),
}));
vi.mock("@/api/billing", () => ({
  billingApi: billingApiMock,
}));

let wrapper: VueWrapper;

beforeEach(() => {
  vi.resetAllMocks();
  i18n.global.locale.value = "en-US";
});

afterEach(() => {
  wrapper?.unmount();
});

async function renderDialog(props = { modelValue: true, hostId: "host-a" }) {
  wrapper = mount(HostRenewalDialog, {
    props,
    attachTo: document.body,
    global: {
      plugins: [i18n],
      stubs: { teleport: true },
    },
  });
  await flushPromises();
}

describe("HostRenewalDialog", () => {
  it("prefills recommended payment and expiry dates and submits renewal", async () => {
    billingApiMock.getDates.mockResolvedValue({
      paymentDate: "2026-04-01",
      serviceExpiryDate: "2026-05-01",
      recommendedNextPaymentDate: "2026-05-01",
    });
    billingApiMock.renew.mockResolvedValue({
      paymentDate: "2026-05-01",
      serviceExpiryDate: "2026-05-01",
      recommendedNextPaymentDate: "2026-06-01",
    });

    await renderDialog();
    expect(billingApiMock.getDates).toHaveBeenCalledWith("host-a", expect.any(AbortSignal));

    const confirmBtn = wrapper.findAll("button").find((b) => b.text().includes("Confirm"));
    expect(confirmBtn).toBeDefined();
    await confirmBtn!.trigger("click");
    await flushPromises();

    expect(billingApiMock.renew).toHaveBeenCalledWith("host-a", {
      next_payment_date: "2026-05-01",
      service_expiry_date: "2026-05-01",
    });
    expect(wrapper.emitted("saved")).toEqual([
      [{ paymentDate: "2026-05-01", serviceExpiryDate: "2026-05-01" }],
    ]);
    expect(wrapper.emitted("update:modelValue")).toEqual([[false]]);
  });

  it("blocks confirmation when service expiry date is empty", async () => {
    billingApiMock.getDates.mockResolvedValue({
      paymentDate: null,
      serviceExpiryDate: null,
      recommendedNextPaymentDate: "2026-05-01",
    });

    await renderDialog();
    const confirmBtn = wrapper.findAll("button").find((b) => b.text().includes("Confirm"));
    await confirmBtn!.trigger("click");
    await flushPromises();

    expect(billingApiMock.renew).not.toHaveBeenCalled();
    expect(wrapper.emitted("saved")).toBeUndefined();
  });
});
