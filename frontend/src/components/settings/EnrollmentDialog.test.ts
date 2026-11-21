// @vitest-environment happy-dom
import { flushPromises, mount, type VueWrapper } from "@vue/test-utils";
import { createPinia } from "pinia";
import { createI18n } from "vue-i18n";
import { afterEach, describe, expect, it, vi } from "vitest";
import { settingsApi, type EnrollmentInvite } from "@/api/settings";
import messages from "@/i18n/locales/en-US.json";
import EnrollmentDialog from "./EnrollmentDialog.vue";

const refreshDashboardHosts = vi.hoisted(() => vi.fn());
vi.mock("@/stores/dashboard", () => ({ useDashboardStore: () => ({ fetchHosts: refreshDashboardHosts }) }));

let wrapper: VueWrapper;
function openDialog() {
  wrapper = mount(EnrollmentDialog, {
    props: { modelValue: true },
    attachTo: document.body,
    global: {
      plugins: [createPinia(), createI18n({ legacy: false, locale: "en-US", messages: { "en-US": messages } })],
      stubs: {
        ElDialog: { props: ["modelValue", "title"], template: '<section v-if="modelValue"><h1>{{ title }}</h1><slot /><slot name="footer" /></section>' },
        ElCollapse: true,
      },
    },
  });
  return wrapper;
}

function invitation(status: EnrollmentInvite["status"] = "issued"): EnrollmentInvite {
  return {
    invite_id: "invite-test", status, expires_at: new Date(Date.now() + 60_000).toISOString(),
    agent_instance_id: "instance-test", agent_port: 8080, stack_root: "/opt/stacks",
    agent_image: "agent", agent_public_host: "agent.example.com", agent_public_url: "https://agent.example.com",
  };
}

async function generate() {
  await wrapper.get('input[placeholder="agent-vps-01.example.com"]').setValue("Agent.example.com.");
  const button = wrapper.findAll("button").find((item) => item.text() === messages["settings.enrollment.generate"]);
  if (!button) throw new Error("Generate invitation button not found");
  await button.trigger("click");
}

afterEach(() => {
  wrapper?.unmount();
  refreshDashboardHosts.mockClear();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("Enrollment dialog lifecycle", () => {
  it("aborts an in-flight list request on close and polls only while open", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
    const list = vi.spyOn(settingsApi, "fetchEnrollmentInvites").mockReturnValueOnce(new Promise(() => {})).mockResolvedValue([]);
    openDialog();
    expect(list).toHaveBeenCalledTimes(1);
    const firstSignal = list.mock.calls[0]?.[0];
    await wrapper.setProps({ modelValue: false });
    expect(firstSignal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(list).toHaveBeenCalledTimes(1);
    await wrapper.setProps({ modelValue: true });
    expect(list).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(5000);
    expect(list).toHaveBeenCalledTimes(3);
  });

  it("normalizes the hostname and only shows an installation command in the session that created it", async () => {
    vi.spyOn(settingsApi, "fetchEnrollmentInvites").mockResolvedValue([invitation()]);
    const create = vi.spyOn(settingsApi, "createEnrollmentInvite").mockResolvedValue({ ...invitation(), install_command: "one-time test command" });
    openDialog();
    await flushPromises();
    await generate();
    await flushPromises();
    expect(create).toHaveBeenCalledWith(expect.objectContaining({ agent_public_host: "agent.example.com" }));
    expect(wrapper.get(".install-command-card code").text()).toBe("one-time test command");
    await wrapper.setProps({ modelValue: false });
    await wrapper.setProps({ modelValue: true });
    await flushPromises();
    expect(wrapper.find(".install-command-card").exists()).toBe(false);
  });
});
