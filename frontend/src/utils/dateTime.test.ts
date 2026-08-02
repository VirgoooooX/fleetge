import { describe, expect, it } from "vitest";
import { remainingInviteSeconds } from "./dateTime";

describe("API date-time helpers", () => {
  it("never returns a negative invite countdown", () => {
    expect(remainingInviteSeconds(
      "2026-01-01T00:00:00Z",
      Date.parse("2026-01-01T00:00:02Z"),
    )).toBe(0);
  });

  it("treats API timestamps without an offset as UTC", () => {
    const now = Date.parse("2026-08-02T08:51:04.401Z");
    expect(remainingInviteSeconds("2026-08-02T09:01:04.401148", now)).toBe(600);
  });
});
