// @vitest-environment happy-dom
import { defineComponent } from "vue";
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useSseOperation } from "./useSseOperation";

const streamSseMock = vi.hoisted(() => vi.fn());
vi.mock("@/api/sse", () => ({
  streamSse: streamSseMock,
}));

function mountHarness() {
  let api!: ReturnType<typeof useSseOperation>;
  const Comp = defineComponent({
    setup() {
      api = useSseOperation();
      return () => null;
    },
  });
  const wrapper = mount(Comp);
  return { wrapper, get api() { return api; } };
}

describe("useSseOperation", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("streams chunks and resolves complete status", async () => {
    streamSseMock.mockImplementationOnce(async ({ onEvent }) => {
      onEvent({ event: "chunk", data: { raw: "Pulling...\r\n" }, rawData: "Pulling...\r\n" });
      onEvent({ event: "complete", data: { status: "success", message: "Updated" }, rawData: "" });
      return { timedOut: false };
    });

    const { api, wrapper } = mountHarness();
    const chunks: string[] = [];
    const res = await api.run({
      hostId: "hk-1",
      stackName: "app",
      action: "update",
      cols: 80,
      rows: 24,
      timeoutMs: 5000,
      onChunk: (c) => chunks.push(c),
    });

    expect(chunks).toEqual(["Pulling...\r\n"]);
    expect(res).toEqual({ kind: "complete", success: true, message: "Updated" });
    wrapper.unmount();
  });

  it("returns timeout and no-result when stream ends without terminal frame", async () => {
    streamSseMock
      .mockResolvedValueOnce({ timedOut: true })
      .mockResolvedValueOnce({ timedOut: false });

    const { api, wrapper } = mountHarness();
    const baseOpts = {
      hostId: "hk-1",
      stackName: "app",
      action: "restart",
      cols: 80,
      rows: 24,
      timeoutMs: 1000,
      onChunk: () => undefined,
    };

    expect(await api.run(baseOpts)).toEqual({ kind: "timeout" });
    expect(await api.run(baseOpts)).toEqual({ kind: "no-result" });
    wrapper.unmount();
  });

  it("returns cancelled when aborted mid-stream", async () => {
    streamSseMock.mockImplementationOnce(async ({ signal }) => {
      expect(signal.aborted).toBe(true);
      return { timedOut: false };
    });

    const { api, wrapper } = mountHarness();
    const res = await api.run({
      hostId: "hk-1",
      stackName: "app",
      action: "stop",
      cols: 80,
      rows: 24,
      timeoutMs: 5000,
      onStart: (cancel) => cancel(),
      onChunk: () => undefined,
    });

    expect(res).toEqual({ kind: "cancelled" });
    wrapper.unmount();
  });
});
