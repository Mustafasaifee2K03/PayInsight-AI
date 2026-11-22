import { describe, expect, it } from "vitest";
import { passwordChecks } from "./api";
import { describeUserAgent } from "../lib/format";

describe("passwordChecks (mirrors backend policy)", () => {
  it("accepts a strong password", () => {
    expect(passwordChecks("Settle-Up#2026", "priya@example.com").every((c) => c.ok)).toBe(true);
  });
  it("flags short, low-variety and email-derived passwords", () => {
    const [len, variety] = passwordChecks("abc", "x@y.com");
    expect(len.ok).toBe(false);
    expect(variety.ok).toBe(false);
    expect(passwordChecks("Priya-2026-xyz", "priya@example.com")[2].ok).toBe(false);
  });
});

describe("describeUserAgent", () => {
  it("summarises common browsers", () => {
    expect(describeUserAgent("Mozilla/5.0 (Windows NT 10.0) AppleWebKit Chrome/131 Safari/537 Edg/131")).toBe("Edge on Windows");
    expect(describeUserAgent(null)).toBe("Unknown device");
  });
});
