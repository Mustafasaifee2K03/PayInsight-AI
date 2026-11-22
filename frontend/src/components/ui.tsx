import { useState, type ReactNode } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, Loader2, TrendingDown, TrendingUp } from "lucide-react";
import type { Kpi } from "../types/api";
import { formatValue } from "../lib/format";

export function KpiCard({ kpi, icon }: { kpi: Kpi; icon?: ReactNode }) {
  const hasChange = kpi.change_abs !== undefined && kpi.change_abs !== null;
  const good = hasChange ? (kpi.change_abs! >= 0) === (kpi.higher_is_better ?? true) : true;
  const flat = hasChange && Math.abs(kpi.change_abs!) < (kpi.unit === "percent" ? 0.05 : 0.5);
  const changeText = hasChange ? (kpi.unit === "percent" ? formatValue(kpi.change_abs, "pp") : formatValue(kpi.change_pct, "pct_change")) : null;
  return (
    <div className={`card p-4 ${kpi.primary ? "ring-1 ring-brand-300" : ""}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-500">{kpi.label}</span>
        {icon && <span className="text-slate-400">{icon}</span>}
      </div>
      <div className="mt-1.5 text-2xl font-semibold tracking-tight text-slate-900 tabular-nums">{kpi.formatted ?? formatValue(kpi.value, kpi.unit)}</div>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500">
        {hasChange && (
          <span className={`inline-flex items-center gap-0.5 font-medium ${flat ? "text-slate-500" : good ? "text-emerald-700" : "text-red-700"}`}>
            {!flat && (kpi.change_abs! >= 0 ? <TrendingUp size={13} /> : <TrendingDown size={13} />)}
            {changeText}
            {kpi.unit === "percent" && kpi.change_pct !== null && kpi.change_pct !== undefined && <span className="font-normal text-slate-400">({formatValue(kpi.change_pct, "pct_change")} rel.)</span>}
          </span>
        )}
        {kpi.previous !== undefined && kpi.previous !== null && <span>prev {formatValue(kpi.previous, kpi.unit)}</span>}
        {kpi.denominator !== undefined && kpi.denominator !== null && (
          <span className="tabular-nums">{formatValue(kpi.numerator, "count")} / {formatValue(kpi.denominator, "count")}</span>
        )}
      </div>
    </div>
  );
}

export function Collapsible({ title, icon, children, defaultOpen = false, badge }: { title: string; icon?: ReactNode; children: ReactNode; defaultOpen?: boolean; badge?: ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-b border-slate-100 last:border-b-0">
      <button className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm font-medium text-slate-700 hover:bg-slate-50" onClick={() => setOpen(!open)}>
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        {icon}
        <span className="flex-1">{title}</span>
        {badge}
      </button>
      {open && <div className="px-4 pb-4 pt-1 text-sm text-slate-700">{children}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500">
      <Loader2 size={16} className="animate-spin" /> {label ?? "Loading…"}
    </div>
  );
}

export function ErrorBox({ title, message, details, reference }: { title?: string; message: string; details?: any; reference?: string }) {
  return (
    <div className="flex gap-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
      <AlertTriangle size={18} className="mt-0.5 shrink-0" />
      <div>
        <div className="font-semibold">{title ?? "Something went wrong"}</div>
        <div className="mt-0.5">{message}</div>
        {reference && <div className="mt-1 font-mono text-xs text-red-700/70">Reference: {reference}</div>}
        {details && <pre className="mt-2 whitespace-pre-wrap text-xs text-red-700/80">{typeof details === "string" ? details : JSON.stringify(details, null, 2)}</pre>}
      </div>
    </div>
  );
}

const SEV: Record<string, string> = {
  pass: "bg-emerald-50 text-emerald-700",
  info: "bg-sky-50 text-sky-700",
  low: "bg-slate-100 text-slate-700",
  medium: "bg-amber-50 text-amber-800",
  high: "bg-red-50 text-red-700",
  OK: "bg-emerald-50 text-emerald-700",
  WARNING: "bg-amber-50 text-amber-800",
  CRITICAL: "bg-red-50 text-red-700",
  MISSING: "bg-purple-50 text-purple-700",
  fail: "bg-red-50 text-red-700",
  warn: "bg-amber-50 text-amber-800",
};

export function Badge({ value, label }: { value: string; label?: string }) {
  return <span className={`chip ${SEV[value] ?? "bg-slate-100 text-slate-700"}`}>{label ?? value}</span>;
}

export function SqlBlock({ sql }: { sql: string }) {
  return <pre className="overflow-x-auto rounded-lg bg-navy-950 p-3 text-xs leading-relaxed text-sky-100">{sql}</pre>;
}
