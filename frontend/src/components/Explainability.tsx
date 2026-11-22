import { useState } from "react";
import { BookOpen, Calendar, CheckCircle2, ClipboardList, Code2, Database, Gauge, MessageSquareText, ShieldAlert, Sigma } from "lucide-react";
import type { AnalysisResult } from "../types/api";
import { Badge, Collapsible, SqlBlock } from "./ui";
import { formatValue } from "../lib/format";

export function Explainability({ r }: { r: AnalysisResult }) {
  const it = r.interpretation ?? {};
  const [q, setQ] = useState(0);
  const query = r.queries?.[q];
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-4 py-2.5">
        <h3 className="text-sm font-semibold text-slate-800">Explainability</h3>
        <span className="text-[11px] text-slate-500">{r.planner.engine} · v{r.planner.version}</span>
      </div>
      <Collapsible title="1. Question interpretation" icon={<MessageSquareText size={15} />} defaultOpen>
        <div className="grid gap-2 sm:grid-cols-2">
          <div><span className="label">Intent</span><div>{it.intent_label} <code className="text-xs text-slate-500">({it.intent})</code></div></div>
          <div><span className="label">Metric</span><div>{it.metric_label}</div></div>
          <div><span className="label">Dimensions</span><div>{it.dimensions?.length ? it.dimensions.map((d) => d.label).join(", ") : "none"}</div></div>
          <div><span className="label">Interpretation confidence (heuristic)</span><div>{Math.round((it.confidence ?? 0) * 100)}%</div></div>
        </div>
        {!!it.matched_terms?.length && (
          <div className="mt-3">
            <span className="label">Recognised terms</span>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {it.matched_terms.map((t, i) => <span key={i} className="chip bg-brand-50 text-brand-700">“{t.term}” → {t.meaning}</span>)}
            </div>
          </div>
        )}
        {!!it.assumptions?.length && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-900">
            <div className="font-semibold">Explicit assumptions</div>
            <ul className="mt-1 list-disc pl-4">{it.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
          </div>
        )}
      </Collapsible>
      <Collapsible title="2. Selected datasets" icon={<Database size={15} />} badge={<span className="text-xs text-slate-400">{r.datasets?.length}</span>}>
        <ul className="space-y-1">{r.datasets?.map((d) => <li key={d.table}><code className="text-brand-700">{d.table}</code> — {d.description}</li>)}</ul>
        <p className="mt-2 text-xs text-slate-500">Derived from the tables actually referenced by the executed SQL (parsed with SQLGlot).</p>
      </Collapsible>
      <Collapsible title="3. Metric definitions" icon={<Sigma size={15} />}>
        <div className="space-y-3">
          {r.metric_definitions?.map((m) => (
            <div key={m.name}>
              <div className="font-medium">{m.label}</div>
              <div className="text-xs text-slate-600">Formula: {m.formula}</div>
              <div className="text-xs text-slate-500">Numerator: <code>{m.numerator}</code>{m.denominator && <> · Denominator: <code>{m.denominator}</code></>}</div>
              {m.notes.map((n, i) => <div key={i} className="text-xs text-slate-500">• {n}</div>)}
            </div>
          ))}
        </div>
      </Collapsible>
      <Collapsible title="4. Analysis plan (validated JSON)" icon={<ClipboardList size={15} />}>
        <SqlBlock sql={JSON.stringify(r.plan, null, 2)} />
      </Collapsible>
      <Collapsible title="5. Date range and filters" icon={<Calendar size={15} />}>
        <div>Current period: <b>{it.time_range?.start}</b> → <b>{it.time_range?.end}</b> ({it.time_range?.days} days, {it.time_range?.label}{it.time_range?.explicit ? "" : ", default"})</div>
        {it.comparison_range && <div>Comparison period: <b>{it.comparison_range.start}</b> → <b>{it.comparison_range.end}</b> ({it.comparison_range.days} days — equal length)</div>}
        <div className="mt-1">Filters: {it.filters?.length ? it.filters.map((f) => `${f.dimension} = ${f.labels.join(", ")}`).join("; ") : "none"}</div>
        <div className="mt-1 text-xs text-slate-500">Boundaries: start 00:00:00 inclusive, end+1 day 00:00:00 exclusive. Relative dates are anchored to the last data day ({r.data_window?.end}), not the machine clock.</div>
      </Collapsible>
      <Collapsible title="6. Generated SQL" icon={<Code2 size={15} />} badge={<span className="text-xs text-slate-400">{r.queries?.length} queries</span>} defaultOpen>
        <div className="mb-2 flex flex-wrap gap-1.5">
          {r.queries?.map((qq, i) => (
            <button key={i} onClick={() => setQ(i)} className={`rounded-md border px-2 py-1 text-xs ${q === i ? "border-brand-500 bg-brand-50 text-brand-700" : "border-slate-200 text-slate-600 hover:bg-slate-50"}`}>
              Q{i + 1}{qq.cached ? " ⚡" : ""}
            </button>
          ))}
        </div>
        {query && (
          <>
            <div className="mb-1 text-xs font-medium text-slate-700">{query.purpose}</div>
            <SqlBlock sql={query.sql} />
            <div className="mt-1.5 text-xs text-slate-500">Bound parameters: <code>{JSON.stringify(query.params)}</code></div>
          </>
        )}
      </Collapsible>
      <Collapsible title="7. Execution metadata" icon={<Gauge size={15} />}>
        <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <div><span className="label">Total time</span><div className="text-sm">{r.execution?.total_ms} ms</div></div>
          <div><span className="label">SQL time</span><div className="text-sm">{r.execution?.sql_ms} ms</div></div>
          <div><span className="label">Queries</span><div className="text-sm">{r.execution?.query_count} ({r.execution?.cache_hits} cached)</div></div>
          <div><span className="label">Rows returned</span><div className="text-sm">{r.execution?.rows_returned}</div></div>
        </div>
        <table className="mt-3 w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th className="py-1">#</th><th>Purpose</th><th>Status</th><th className="text-right">ms</th><th className="text-right">Rows</th><th>Cache</th></tr></thead>
          <tbody>
            {r.queries?.map((qq, i) => (
              <tr key={i} className="border-t border-slate-100">
                <td className="py-1">Q{i + 1}</td><td className="pr-2">{qq.purpose}</td>
                <td><span className="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 size={12} />{qq.status}</span></td>
                <td className="text-right tabular-nums">{qq.duration_ms.toFixed(1)}</td><td className="text-right tabular-nums">{qq.row_count}{qq.truncated ? "+" : ""}</td>
                <td>{qq.cached ? "hit" : "miss"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-slate-500">Each query passed the SQLGlot validator, the SQLite authorizer (SELECT/READ only) and ran on a read-only connection with a timeout and row cap.</p>
      </Collapsible>
      <Collapsible title="8. Data-quality warnings" icon={<ShieldAlert size={15} />}
        badge={<Badge value={r.data_quality?.status ?? "pass"} label={`${r.data_quality?.warnings.filter((w) => w.severity !== "info").length ?? 0} open`} />}>
        {r.data_quality?.warnings.length ? (
          <ul className="space-y-2">
            {r.data_quality.warnings.map((w, i) => (
              <li key={i} className="text-xs">
                <div className="flex items-center gap-2"><Badge value={w.severity} /> <b>{w.check}</b> — {formatValue(w.affected, "count")} records</div>
                <div className="text-slate-600">Impact: {w.impact}</div>
                <div className="text-slate-500">Treatment: {w.treatment}</div>
              </li>
            ))}
          </ul>
        ) : <div className="text-emerald-700">All data-quality checks passed.</div>}
        <div className="mt-2 text-xs text-slate-500">Raw rows {formatValue(r.data_quality?.raw_rows, "count")} → canonical {formatValue(r.data_quality?.canonical_rows, "count")} after duplicate resolution.</div>
      </Collapsible>
      <Collapsible title="9. Evidence (query result previews)" icon={<BookOpen size={15} />}>
        {r.queries?.map((qq, i) => (
          <div key={i} className="mb-3">
            <div className="text-xs font-medium text-slate-700">Q{i + 1}. {qq.purpose} <span className="text-slate-400">({qq.row_count} rows)</span></div>
            <div className="mt-1 max-h-48 overflow-auto rounded border border-slate-200">
              <table className="w-full text-[11px]">
                <thead className="sticky top-0 bg-slate-50"><tr>{qq.columns?.map((c) => <th key={c} className="px-2 py-1 text-left font-semibold text-slate-500">{c}</th>)}</tr></thead>
                <tbody>
                  {qq.preview?.map((row, j) => (
                    <tr key={j} className="border-t border-slate-100">{qq.columns?.map((c) => <td key={c} className="whitespace-nowrap px-2 py-0.5 tabular-nums">{typeof row[c] === "number" && !Number.isInteger(row[c]) ? row[c].toFixed(3) : String(row[c] ?? "NULL")}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </Collapsible>
    </div>
  );
}
