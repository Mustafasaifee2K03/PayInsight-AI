import { describe, expect, it } from "vitest";
import { formatINR, formatValue, shortDay, toCSV } from "./format";

describe("formatINR", () => {
  it("formats crores, lakhs and rupees from paise", () => {
    expect(formatINR(98_400_000_00)).toBe("₹9.84 Cr");
    expect(formatINR(1_250_000_00)).toBe("₹12.50 L");
    expect(formatINR(1234_56)).toBe("₹1,235");
    expect(formatINR(null)).toBe("—");
  });
});

describe("formatValue", () => {
  it("distinguishes percentage points from percent change", () => {
    expect(formatValue(-2.9, "pp")).toBe("-2.90 pp");
    expect(formatValue(1.25, "pp")).toBe("+1.25 pp");
    expect(formatValue(-3.2, "pct_change")).toBe("-3.2%");
    expect(formatValue(91.756, "percent")).toBe("91.76%");
  });
  it("handles nulls and counts", () => {
    expect(formatValue(null, "count")).toBe("—");
    expect(formatValue(30000, "count")).toBe("30,000");
    expect(formatValue(true, "bool")).toBe("Yes");
  });
});

describe("toCSV", () => {
  it("escapes quotes, commas and newlines", () => {
    const csv = toCSV([{ key: "a", label: "Name" }, { key: "b", label: "Value" }], [{ a: 'Acme, "Ltd"', b: 1 }, { a: "x\ny", b: null }]);
    expect(csv).toBe('Name,Value\r\n"Acme, ""Ltd""",1\r\n"x\ny",');
  });
});

describe("shortDay", () => {
  it("shortens ISO dates", () => {
    expect(shortDay("2025-10-24")).toBe("24 Oct");
    expect(shortDay("Bank")).toBe("Bank");
  });
});
