import { onBeforeUnmount } from "vue";
import { streamSse } from "@/api/sse";

export type SseOperationResult =
  | { kind: "complete"; success: boolean; message?: string }
  | { kind: "error"; message?: string }
  | { kind: "request-error"; message?: string }
  | { kind: "timeout" }
  | { kind: "cancelled" }
  | { kind: "no-result" };

export function useSseOperation() {
  let active: AbortController | null = null;

  function cancel() {
    active?.abort();
  }

  function discard() {
    cancel();
    active = null;
  }

  onBeforeUnmount(discard);

  async function run(options: {
    hostId: string;
    stackName: string;
    action: string;
    cols: number;
    rows: number;
    timeoutMs: number;
    onStart?: (cancel: () => void) => void;
    onChunk: (chunk: string) => void;
  }): Promise<SseOperationResult | undefined> {
    discard();
    const controller = new AbortController();
    active = controller;
    let result: SseOperationResult | undefined;

    const { hostId, stackName, action, cols, rows, timeoutMs, onStart, onChunk } = options;
    try {
      onStart?.(() => controller.abort());
      const { timedOut } = await streamSse({
        url: `/api/hosts/${encodeURIComponent(hostId)}/stacks/${encodeURIComponent(stackName)}/${action}?cols=${cols}&rows=${rows}`,
        method: "POST",
        signal: controller.signal,
        timeoutMs,
        onEvent: (frame) => {
          if (active !== controller || controller.signal.aborted || result) return;
          if (frame.event === "chunk") onChunk(frame.data?.raw ?? frame.rawData);
          else if (frame.event === "line") onChunk(frame.data?.text ?? frame.rawData);
          else if (frame.event === "complete" || frame.event === "error") {
            const message = typeof frame.data?.message === "string" ? frame.data.message : undefined;
            result = frame.event === "complete"
              ? { kind: "complete", success: frame.data?.status === "success", message }
              : { kind: "error", message };
          }
        },
      });
      if (active !== controller) return;
      if (result) return result;
      if (controller.signal.aborted) return { kind: "cancelled" };
      return { kind: timedOut ? "timeout" : "no-result" };
    } catch (error) {
      if (active !== controller) return;
      if (result) return result;
      if (controller.signal.aborted) return { kind: "cancelled" };
      return { kind: "request-error", message: error instanceof Error ? error.message : undefined };
    } finally {
      if (active === controller) active = null;
    }
  }

  return { run, cancel, discard };
}
