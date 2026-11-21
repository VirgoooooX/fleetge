import { t } from "@/i18n";
import { redirectToLogin } from "./authRedirect";

export type SseFrame = {
  event: string;
  data: any;
  rawData: string;
};

export type StreamSseOptions = {
  url: string;
  method?: string;
  headers?: Record<string, string>;
  body?: BodyInit | null;
  timeoutMs?: number;
  signal?: AbortSignal;
  onEvent: (frame: SseFrame) => void;
  onTimeout?: () => void;
};

class SseParser {
  private buffer = "";
  private previousEndedWithCr = false;

  feed(chunk: string): Array<{ event: string; data: string }> {
    if (!chunk) return [];
    const continuation = this.previousEndedWithCr && chunk.startsWith("\n") ? chunk.slice(1) : chunk;
    this.previousEndedWithCr = chunk.endsWith("\r");
    this.buffer += continuation.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    const events: Array<{ event: string; data: string }> = [];

    let boundaryIndex: number;
    while ((boundaryIndex = this.buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = this.buffer.slice(0, boundaryIndex);
      this.buffer = this.buffer.slice(boundaryIndex + 2);
      const parsed = this.parseBlock(rawEvent);
      if (parsed) events.push(parsed);
    }

    return events;
  }

  flush(): Array<{ event: string; data: string }> {
    if (!this.buffer.trim()) {
      this.buffer = "";
      return [];
    }
    const parsed = this.parseBlock(this.buffer);
    this.buffer = "";
    return parsed ? [parsed] : [];
  }

  private parseBlock(rawEvent: string): { event: string; data: string } | null {
    if (!rawEvent.trim()) return null;
    const lines = rawEvent.split("\n");
    let event = "message";
    const dataLines: string[] = [];

    for (const line of lines) {
      if (line.startsWith(":")) continue;
      if (line.startsWith("event:")) {
        event = line.slice(6).replace(/^ /, "");
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).replace(/^ /, ""));
      }
    }

    if (dataLines.length === 0) return null;
    return { event, data: dataLines.join("\n") };
  }
}

function parsePayload(rawData: string) {
  if (!rawData) return null;
  try {
    return JSON.parse(rawData);
  } catch {
    return rawData;
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  const fallback = `HTTP ${response.status}`;
  try {
    const text = await response.text();
    if (!text) return fallback;
    try {
      const body = JSON.parse(text);
      const detail = body?.detail ?? body?.message;
      return typeof detail === "string" && detail.trim() ? detail : text;
    } catch {
      return text;
    }
  } catch {
    return fallback;
  }
}

export async function streamSse(options: StreamSseOptions): Promise<{ timedOut: boolean }> {
  const token = localStorage.getItem("token");
  const controller = new AbortController();
  let timedOut = false;
  let completed = false;

  const abortFromExternalSignal = () => {
    completed = true;
    controller.abort();
  };

  if (options.signal?.aborted) {
    abortFromExternalSignal();
  } else {
    options.signal?.addEventListener("abort", abortFromExternalSignal, { once: true });
  }

  const timeoutId = options.timeoutMs
    ? window.setTimeout(() => {
        if (completed) return;
        timedOut = true;
        completed = true;
        options.onTimeout?.();
        controller.abort();
      }, options.timeoutMs)
    : null;

  try {
    if (controller.signal.aborted) return { timedOut };
    const response = await fetch(options.url, {
      method: options.method || "GET",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        Accept: "text/event-stream",
        ...options.headers,
      },
      body: options.body ?? null,
      signal: controller.signal,
    });

    if (!response.ok) {
      if (response.status === 401) redirectToLogin();
      throw new Error(await readErrorDetail(response));
    }
    if (!response.body) {
      throw new Error(t("sse.streamNotSupported"));
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();
    let reachedEnd = false;

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          reachedEnd = true;
          const rest = decoder.decode();
          for (const ev of parser.feed(rest).concat(parser.flush())) {
            options.onEvent({
              event: ev.event,
              rawData: ev.data,
              data: parsePayload(ev.data),
            });
          }
          break;
        }

        const text = decoder.decode(value, { stream: true });
        for (const ev of parser.feed(text)) {
          options.onEvent({
            event: ev.event,
            rawData: ev.data,
            data: parsePayload(ev.data),
          });
        }
      }
    } finally {
      if (!reachedEnd) void reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }

    completed = true;
    return { timedOut };
  } catch (error) {
    if (timedOut) return { timedOut: true };
    if (options.signal?.aborted) return { timedOut: false };
    throw error;
  } finally {
    completed = true;
    options.signal?.removeEventListener("abort", abortFromExternalSignal);
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
    }
  }
}
