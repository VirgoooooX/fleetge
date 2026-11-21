import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useDashboardStore, type UpdateRunItem } from "./dashboard";
import { apiClient } from "@/api/client";
import { streamSse } from "@/api/sse";

vi.mock("@/api/sse", () => ({ streamSse: vi.fn() }));
vi.mock("@/api/client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

const run = (id: number, host_id: string, status: UpdateRunItem["status"]): UpdateRunItem => ({
  id, host_id, request_id: `request-${id}`, source: "manual", requested_by: "admin",
  stack_name: "app", status, stage: status, attempts: 1, detail: "", log_tail: "",
  targets_json: "{}", started_at: "2026-10-19T00:00:00Z",
});

beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); setActivePinia(createPinia()); });
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllTimers(); vi.useRealTimers(); });

describe("update run selection", () => {
  it("shows the active update instead of an older failure on the same Stack", () => {
    const store = useDashboardStore();
    store.updateRunsByHost.a = { active: [run(3, "a", "running")], recent: [run(2, "a", "failed")] };
    expect(store.updateRunForStack("a", "app")?.id).toBe(3);
  });

  it("keeps same-named Stacks on different hosts separate", () => {
    const store = useDashboardStore();
    store.updateRunsByHost.a = { active: [run(3, "a", "running")], recent: [] };
    store.updateRunsByHost.b = { active: [], recent: [run(4, "b", "success"), run(1, "b", "failed")] };
    expect(store.updateRunForStack("a", "app")?.id).toBe(3);
    expect(store.updateRunForStack("b", "app")?.id).toBe(4);
  });

  it("remembers a watched update after it finishes while the user is away", async () => {
    const store = useDashboardStore();
    vi.mocked(apiClient.get).mockResolvedValueOnce({data: {active: [run(5, "a", "running")], recent: []}});
    await store.fetchUpdateRuns("a");
    vi.mocked(apiClient.get).mockResolvedValueOnce({data: {active: [], recent: [run(5, "a", "success")]}});
    await store.fetchUpdateRuns("a");
    expect(store.observedUpdateRunIds["a/app"]).toBe(5);
    expect(store.updateRunForStack("a", "app")?.status).toBe("success");
  });

  it("counts partially successful runs as a finished result", () => {
    const store = useDashboardStore();
    const partial = run(6, "a", "partial");
    store.updateRunsByHost.a = { active: [], recent: [partial] };
    const batch = store.updateRunBatchForRequest("a", partial.request_id);
    expect(batch?.finished).toBe(true);
    expect(batch?.counts.partial).toBe(1);
    expect(batch?.counts.success).toBe(0);
    expect(store.updateRunForStack("a", "app")?.status).toBe("partial");
  });

  it("reuses the original request ID after an unconfirmed submission", async () => {
    const store = useDashboardStore();
    vi.mocked(apiClient.post).mockRejectedValue(new Error("connection lost"));
    vi.mocked(apiClient.get).mockRejectedValue({ response: { status: 404 } });
    await expect(store.submitUpdateRuns("a", "manual", ["app"])).rejects.toThrow();
    const original = vi.mocked(apiClient.post).mock.calls[0][1] as {request_id: string};
    vi.mocked(apiClient.post).mockResolvedValue({ data: {host_id: "a",request_id: original.request_id,mode: "manual",items: [],finished: true,counts: {}} });
    await store.submitUpdateRuns("a", "manual", ["app"]);
    expect(vi.mocked(apiClient.post).mock.calls[1][1]).toMatchObject({request_id: original.request_id});
  });
});


describe("dashboard polling lifecycle", () => {
  it("does not restart polling when a list response arrives after stop", async () => {
    const store = useDashboardStore();
    vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { active: [run(7, "a", "running")], recent: [] } });
    const pending = store.fetchUpdateRuns("a");
    store.stopPolling();
    await pending;
    expect(store.updateRunForStack("a", "app")?.status).toBe("running");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps a submitted batch when an older list response resolves later", async () => {
    const store = useDashboardStore();
    let finishList!: (response: Awaited<ReturnType<typeof apiClient.get>>) => void;
    vi.mocked(apiClient.get).mockReturnValueOnce(new Promise((resolve) => { finishList = resolve; }));
    vi.mocked(apiClient.post).mockResolvedValueOnce({ data: { host_id: "a", items: [run(8, "a", "queued")] } });
    const pending = store.fetchUpdateRuns("a");
    await store.submitUpdateRuns("a", "manual", ["app"]);
    finishList({ data: { active: [], recent: [] } } as Awaited<ReturnType<typeof apiClient.get>>);
    await pending;
    expect(store.updateRunForStack("a", "app")?.id).toBe(8);
    store.$dispose();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("backs off after disconnects and cancels the pending reconnect on stop", async () => {
    vi.stubGlobal("document", { hidden: false, addEventListener: vi.fn(), removeEventListener: vi.fn() });
    vi.mocked(apiClient.get).mockResolvedValue({ data: [], headers: {} });
    vi.mocked(streamSse).mockResolvedValue({ timedOut: false });
    const store = useDashboardStore();
    store.startPolling({ metrics: false, structureInterval: 10 });
    expect(streamSse).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(streamSse).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1999);
    expect(streamSse).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(streamSse).toHaveBeenCalledTimes(3);
    store.stopPolling();
    await vi.advanceTimersByTimeAsync(30000);
    expect(streamSse).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });
});
