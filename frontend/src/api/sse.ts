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

  feed(chunk: string): Array<{ event: string; data: string }> {
    this.buffer += chunk;
    const events: Array<{ event: string; data: string }> = [];

    let boundaryIndex: number;
    while ((boundaryIndex = this.buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = this.buffer.slice(0, boundaryIndex);
      this.buffer = this.buffer.slice(boundaryIndex + 2);
      if (!rawEvent.trim()) continue;

      const lines = rawEvent.split("\n");
      let event = "message";
      const dataLines: string[] = [];

      for (const line of lines) {
        if (line.startsWith("event: ")) {
          event = line.slice(7);
        } else if (line.startsWith("data: ")) {
          dataLines.push(line.slice(6));
        }
      }

      if (dataLines.length > 0) {
        events.push({ event, data: dataLines.join("\n") });
      }
    }

    return events;
  }
}

function redirectToLogin() {
  localStorage.removeItem("token");
  localStorage.removeItem("username");
  if (window.location.pathname !== "/login") {
    const redirect = `${window.location.pathname}${window.location.search}`;
    window.location.replace(`/login?redirect=${encodeURIComponent(redirect)}`);
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
  let detail = `HTTP ${response.status}`;
  try {
    const body = await response.json();
    detail = body.detail || body.message || detail;
  } catch {
    try {
      const text = await response.text();
      if (text) detail = text;
    } catch {
      // keep status detail
    }
  }
  return detail;
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
      throw new Error("浏览器不支持流式读取");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

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
