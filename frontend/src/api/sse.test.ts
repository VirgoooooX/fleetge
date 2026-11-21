// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { streamSse, type SseFrame } from "./sse";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function responseWithChunks(...chunks: Uint8Array[]) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  }));
}

describe("streamSse", () => {
  it("preserves split CRLF, UTF-8 and multiline payloads and flushes the final frame", async () => {
    const encoder = new TextEncoder();
    const tail = encoder.encode('港"}\r\n\r\n: keepalive\r\ndata: one\r\ndata: two');
    const fetch = vi.fn().mockResolvedValue(responseWithChunks(
      encoder.encode('event: progress\r'),
      encoder.encode('\ndata: {"port":"'),
      tail.slice(0, 1),
      tail.slice(1),
    ));
    vi.stubGlobal("fetch", fetch);
    const frames: SseFrame[] = [];
    expect(await streamSse({ url: "/events", onEvent: (frame) => frames.push(frame) })).toEqual({ timedOut: false });
    expect(frames).toEqual([
      { event: "progress", data: { port: "港" }, rawData: '{"port":"港"}' },
      { event: "message", data: "one\ntwo", rawData: "one\ntwo" },
    ]);
  });

  it("reports a timeout and aborts the pending request", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", (_url: string, { signal }: RequestInit) => new Promise((_resolve, reject) => {
      signal?.addEventListener("abort", () => reject(signal.reason), { once: true });
    }));
    const onTimeout = vi.fn();
    const operation = streamSse({ url: "/events", timeoutMs: 1000, onTimeout, onEvent: vi.fn() });
    await vi.advanceTimersByTimeAsync(1000);
    expect(await operation).toEqual({ timedOut: true });
    expect(onTimeout).toHaveBeenCalledOnce();
  });

  it("skips fetch when the caller already cancelled", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();
    controller.abort();
    expect(await streamSse({ url: "/events", signal: controller.signal, onEvent: vi.fn() }))
      .toEqual({ timedOut: false });
    expect(fetch).not.toHaveBeenCalled();
  });
});
