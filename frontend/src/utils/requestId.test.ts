import { afterEach, describe, expect, it, vi } from "vitest";
import { createRequestId } from "./requestId";

afterEach(() => vi.unstubAllGlobals());

describe("update submission request IDs", () => {
  it("generates UUID v4 on HTTP origins without crypto.randomUUID", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => bytes.fill(255),
    });
    expect(createRequestId()).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff");
  });

  it("generates distinct IDs with browser random bytes", () => {
    const ids = Array.from({ length: 100 }, () => createRequestId());
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    }
  });
});
