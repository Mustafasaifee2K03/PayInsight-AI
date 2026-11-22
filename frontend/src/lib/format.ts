import type { CellFormat } from "../types/api";

const nf = new Intl.NumberFormat("en-IN");

export function formatINR(minor: number | null | undefined): string {
  if (minor === null || minor === undefined || Number.isNaN(minor)) return "—";
  const rupees = minor / 100;
  const abs = Math.abs(rupees);
  if (abs >= 1e7) return `₹${(rupees / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `₹${(rupees / 1e5).toFixed(2)} L`;
  return `₹${nf.format(Math.round(rupees))}`;
}

export function formatValue(v: any, fmt: CellFormat | string): string {
  if (v === null || v === undefined || (typeof v === "number" && Number.isNaN(v))) return "—";
  switch (fmt) {
    case "count":
      return nf.format(Math.round(v));
    case "count_change":
      return `${v > 0 ? "+" : ""}${nf.format(Math.round(v))}`;
    case "percent":
      return `${Number(v).toFixed(2)}%`;
    case "pp":
      return `${v > 0 ? "+" : ""}${Number(v).toFixed(2)} pp`;
    case "pct_change":
      return `${v > 0 ? "+" : ""}${Number(v).toFixed(1)}%`;
    case "currency_minor":
      return formatINR(v);
    case "number":
      return Number(v).toFixed(2);
    case "bool":
      return v ? "Yes" : "No";
    default:
      return String(v);
  }
}

/** Compact axis tick formatting. */
export function formatTick(v: any, unit: string): string {
  if (typeof v !== "number") return String(v);
  if (unit === "percent") return `${v.toFixed(0)}%`;
  if (unit === "pp") return `${v.toFixed(1)}`;
  if (unit === "currency_minor") return formatINR(v);
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(1)}k`;
  return String(Math.round(v * 100) / 100);
}

export function shortDay(d: string): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return d;
  const [, m, day] = d.split("-");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(day)} ${months[Number(m) - 1]}`;
}

function csvCell(v: any): string {
  if (v === null || v === undefined) return "";
  const s = typeof v === "object" ? JSON.stringify(v) : String(v);
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCSV(columns: { key: string; label: string }[], rows: Record<string, any>[]): string {
  const head = columns.map((c) => csvCell(c.label)).join(",");
  const body = rows.map((r) => columns.map((c) => csvCell(r[c.key])).join(","));
  return [head, ...body].join("\r\n");
}

export function downloadCSV(filename: string, csv: string) {
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Categorical palette (validated reference palette, light mode), assigned in fixed order. */
export const SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
export const PREVIOUS_COLOR = "#86b6ef";
export const CURRENT_COLOR = "#1c5cab";

/** "2026-11-21T06:09:00+00:00" -> "21 Nov 2026, 11:39" in the viewer's local time. */
export function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) return "—";
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return isoString;
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

/** Very small user-agent summariser for the sessions list (no external library). */
export function describeUserAgent(ua: string | null | undefined): string {
  if (!ua) return "Unknown device";
  const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari"
    : /python-httpx|testclient/i.test(ua) ? "API client" : "Browser";
  const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Mac OS X/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${browser} on ${os}` : browser;
}
