import { useEffect, useState } from "react";
import { Database, GitCompare, Lock, Play, ShieldCheck, Terminal } from "lucide-react";
import { api, ApiError } from "../services/api";
import type { User } from "../types/api";
import { Badge, ErrorBox, SqlBlock, Spinner } from "../components/ui";
import { downloadCSV, formatValue, toCSV } from "../lib/format";

export function DataQualityPage({ user, refreshKey }: { user: User; refreshKey: number }) {
  const [quality, setQuality] = useState<any>(null);
  const [recon, setRecon] = useState<any>(null);
  const [datasets, setDatasets] = useState<any>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [tab, setTab] = useState<"quality" | "recon" | "catalog" | "sql">("quality");
  const allowed = user.permissions.includes("quality");

  useEffect(() => {
    setQuality(null); setRecon(null); setError(null);
    api.datasets().then(setDatasets).catch(() => undefined);
    if (!allowed) return;
    api.quality().then(setQuality).catch(setError);
    api.reconciliation().then(setRecon).catch(setError);
  }, [refreshKey, allowed]);

  const tabs = [
    { id: "quality", label: "Data-quality checks", icon: <ShieldCheck size={15} /> },
    { id: "recon", label: "Source reconciliation", icon: <GitCompare size={15} /> },
    { id: "catalog", label: "Dataset catalogue", icon: <Database size={15} /> },
    { id: "sql", label: "SQL safety sandbox", icon: <Terminal size={15} /> },
  ] as const;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Data quality & sources</h1>
        <p className="text-sm text-slate-500">Nothing is silently discarded: every issue shows its count, impact and the treatment applied by the metric engine.</p>
      </div>
      <div className="flex flex-wrap gap-1 border-b border-slate-200">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm ${tab === t.id ? "border-brand-500 font-medium text-brand-700" : "border-transparent text-slate-500 hover:text-slate-700"}`}>
            {t.icon}{t.label}
          </button>
        ))}
      </div>
      {!allowed && tab !== "catalog" ? (
        <div className="card flex items-center gap-3 p-6 text-sm text-slate-600"><Lock size={18} /> Data-quality reports, reconciliation and the SQL sandbox require the ADMIN role (enforced by the backend — requests return HTTP 403).</div>
      ) : error && tab !== "catalog" ? <ErrorBox message={error.message} /> : (
        <>
          {tab === "quality" && (quality ? <QualityView q={quality} /> : <Spinner />)}
          {tab === "recon" && (recon ? <ReconView r={recon} /> : <Spinner />)}
          {tab === "sql" && <SqlSandbox />}
        </>
      )}
      {tab === "catalog" && (datasets ? <CatalogView d={datasets} /> : <Spinner />)}
    </div>
  );
}

function QualityView({ q }: { q: any }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Overall status" value={<Badge value={q.status} label={q.status.toUpperCase()} />} />
        <Stat label="Open issues" value={q.issues} />
        <Stat label="Raw rows (transactions_raw)" value={formatValue(q.raw_rows, "count")} />
        <Stat label="Canonical rows (deduplicated)" value={formatValue(q.canonical_rows, "count")} />
      </div>
      <div className="rounded-lg bg-brand-50 px-4 py-2.5 text-sm text-brand-700"><b>Duplicate-resolution rule:</b> {q.duplicate_rule}</div>
      <div className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
          <h3 className="text-sm font-semibold">Checks (data profile <code>{q.data_profile}</code>)</h3>
          <button className="btn-ghost !py-1 text-xs" onClick={() => downloadCSV("data_quality.csv", toCSV(
            [{ key: "name", label: "Check" }, { key: "affected", label: "Affected" }, { key: "severity", label: "Severity" }, { key: "impact", label: "Impact" }, { key: "treatment", label: "Treatment" }], q.checks))}>CSV</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500">
              <tr><th className="px-3 py-2">Check</th><th className="px-3 py-2 text-right">Affected</th><th className="px-3 py-2">Severity</th><th className="px-3 py-2">Explanation & impact</th><th className="px-3 py-2">Treatment applied</th></tr>
            </thead>
            <tbody>
              {q.checks.map((c: any) => (
                <tr key={c.id} className={`border-t border-slate-100 align-top ${c.severity === "high" ? "bg-red-50/40" : ""}`}>
                  <td className="px-3 py-2 font-medium text-slate-800">{c.name}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatValue(c.affected, "count")}<div className="text-[11px] text-slate-400">{c.pct_of_rows}%</div></td>
                  <td className="px-3 py-2"><Badge value={c.severity} /></td>
                  <td className="max-w-sm px-3 py-2 text-xs text-slate-600">{c.explanation}<div className="mt-1 text-slate-500"><b>Impact:</b> {c.impact}</div></td>
                  <td className="max-w-xs px-3 py-2 text-xs text-slate-600">{c.treatment}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function ReconView({ r }: { r: any }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <Stat label="Status" value={<Badge value={r.status} label={r.status.toUpperCase()} />} />
        <Stat label="Bank-days compared" value={r.compared_rows} />
        <Stat label="Flagged bank-days" value={r.flagged_count} />
        <Stat label="Thresholds" value={<span className="text-sm">warn ≥ {r.thresholds.warning_pct}% · critical ≥ {r.thresholds.critical_pct}%</span>} />
      </div>
      <div className="rounded-lg bg-slate-100 px-4 py-2.5 text-xs text-slate-700">
        <b>Source A:</b> {r.source_a} · <b>Source B:</b> {r.source_b}<br />{r.policy}
      </div>
      <div className="card overflow-hidden">
        <div className="border-b border-slate-100 px-4 py-2.5 text-sm font-semibold">Flagged discrepancies</div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs text-slate-500">
              <tr><th className="px-3 py-2">Date</th><th className="px-3 py-2">Bank</th><th className="px-3 py-2">Metric</th><th className="px-3 py-2 text-right">Source A</th><th className="px-3 py-2 text-right">Source B</th><th className="px-3 py-2 text-right">Abs. diff</th><th className="px-3 py-2 text-right">% diff</th><th className="px-3 py-2">Status</th></tr>
            </thead>
            <tbody>
              {r.flagged.flatMap((f: any) => Object.entries(f.metrics).filter(([, m]: any) => m.status !== "OK").map(([name, m]: any) => (
                <tr key={f.report_date + f.bank_id + name} className="border-t border-slate-100">
                  <td className="px-3 py-1.5">{f.report_date}</td><td className="px-3 py-1.5">{f.bank_name}</td><td className="px-3 py-1.5">{name}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{formatValue(m.source_a, "count")}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{m.source_b === null ? "missing" : formatValue(m.source_b, "count")}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{m.abs_discrepancy === null ? "—" : formatValue(m.abs_discrepancy, "count_change")}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{m.pct_discrepancy === null ? "—" : `${m.pct_discrepancy.toFixed(2)}%`}</td>
                  <td className="px-3 py-1.5"><Badge value={m.status} /></td>
                </tr>
              )))}
              {!r.flagged.length && <tr><td colSpan={8} className="px-3 py-6 text-center text-emerald-700">All bank-reported daily counts match transaction-derived counts.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <div className="card overflow-hidden">
        <div className="border-b border-slate-100 px-4 py-2.5 text-sm font-semibold">Per-bank summary (full window)</div>
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500"><tr><th className="px-3 py-2">Bank</th><th className="px-3 py-2 text-right">Days</th><th className="px-3 py-2 text-right">OK</th><th className="px-3 py-2 text-right">Warning</th><th className="px-3 py-2 text-right">Critical</th><th className="px-3 py-2 text-right">Missing</th><th className="px-3 py-2 text-right">Source A total</th><th className="px-3 py-2 text-right">Source B total</th></tr></thead>
          <tbody>{r.banks.map((b: any) => (
            <tr key={b.bank_id} className="border-t border-slate-100"><td className="px-3 py-1.5">{b.bank_name}</td><td className="px-3 py-1.5 text-right">{b.days}</td><td className="px-3 py-1.5 text-right">{b.ok}</td><td className="px-3 py-1.5 text-right">{b.warning}</td><td className="px-3 py-1.5 text-right">{b.critical}</td><td className="px-3 py-1.5 text-right">{b.missing}</td><td className="px-3 py-1.5 text-right tabular-nums">{formatValue(b.source_a_total, "count")}</td><td className="px-3 py-1.5 text-right tabular-nums">{formatValue(b.source_b_total, "count")}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <details className="text-xs"><summary className="cursor-pointer text-slate-500">Reconciliation SQL</summary><div className="mt-2"><SqlBlock sql={r.query.sql} /></div></details>
    </div>
  );
}

function CatalogView({ d }: { d: any }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {d.tables.map((t: any) => (
          <div key={t.name} className="card p-4">
            <div className="flex items-center justify-between"><code className="text-sm font-semibold text-brand-700">{t.name}</code><span className="text-xs text-slate-500">{formatValue(t.row_count, "count")} rows</span></div>
            <p className="mt-1 text-xs text-slate-600">{t.description}</p>
            <div className="mt-2 flex flex-wrap gap-1">{t.columns.map((c: string) => <span key={c} className="chip bg-slate-100 text-slate-600">{c}</span>)}</div>
          </div>
        ))}
      </div>
      <div className="card p-4 text-sm">
        <div className="label mb-2">Relationships (foreign keys)</div>
        <ul className="grid gap-1 text-xs md:grid-cols-2">{d.relationships.map((r: any) => <li key={r.from}><code>{r.from}</code> → <code>{r.to}</code></li>)}</ul>
        <div className="label mb-1 mt-4">Generation metadata</div>
        <div className="flex flex-wrap gap-2 text-xs">{Object.entries(d.metadata).map(([k, v]) => <span key={k} className="chip bg-slate-100 text-slate-700">{k}: {String(v)}</span>)}</div>
      </div>
    </div>
  );
}

const SAMPLES = [
  "SELECT b.bank_name, COUNT(*) AS attempts FROM transactions_canonical t JOIN banks b ON b.bank_id = t.bank_id GROUP BY b.bank_name",
  "DROP TABLE transactions_raw",
  "SELECT * FROM banks; DELETE FROM banks",
  "SELECT * FROM sqlite_master",
  "UPDATE merchants SET risk_tier = 'LOW'",
  "SELECT COUNT(*) FROM transactions_canonical a, transactions_canonical b",
];

function SqlSandbox() {
  const [sql, setSql] = useState(SAMPLES[0]);
  const [out, setOut] = useState<any>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  async function go(execute: boolean) {
    setBusy(true); setErr(null); setOut(null);
    try { setOut({ execute, ...(execute ? await api.executeSql(sql) : await api.validateSql(sql)) }); }
    catch (e) { setErr(e as ApiError); }
    finally { setBusy(false); }
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">Try to break the SQL safety layer. Every statement goes through the SQLGlot AST validator, the SQLite authorizer and a read-only, time-limited connection (ADMIN only).</p>
      <div className="flex flex-wrap gap-1.5">{SAMPLES.map((s) => <button key={s} onClick={() => setSql(s)} className="chip max-w-xs truncate bg-slate-100 text-slate-700 hover:bg-slate-200">{s}</button>)}</div>
      <textarea value={sql} onChange={(e) => setSql(e.target.value)} rows={4} className="w-full rounded-lg border border-slate-300 p-3 font-mono text-xs outline-none focus:border-brand-500" />
      <div className="flex gap-2">
        <button className="btn-outline" disabled={busy} onClick={() => go(false)}><ShieldCheck size={15} /> Validate</button>
        <button className="btn-primary" disabled={busy} onClick={() => go(true)}><Play size={15} /> Validate & execute</button>
      </div>
      {busy && <Spinner label="Running…" />}
      {err && <ErrorBox title={`Rejected — ${err.code} (HTTP ${err.status})`} message={err.message} details={err.details?.reasons} reference={err.requestId} />}
      {out && !out.execute && (
        out.valid ? <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">Valid. Tables: {out.tables.join(", ")}.{out.limit_applied && ` Row limit ${out.limit_applied} enforced.`}<div className="mt-2"><SqlBlock sql={out.executed_sql} /></div></div>
          : <ErrorBox title="Rejected by validator" message={out.reasons.join(" ")} />
      )}
      {out && out.execute && (
        <div className="card overflow-hidden">
          <div className="border-b border-slate-100 px-4 py-2 text-xs text-slate-500">{out.row_count} rows · {out.duration_ms} ms · tables {out.tables.join(", ")}{out.truncated ? " · truncated" : ""}</div>
          <div className="max-h-80 overflow-auto"><table className="w-full text-xs"><thead className="sticky top-0 bg-slate-50"><tr>{out.columns.map((c: string) => <th key={c} className="px-2 py-1 text-left">{c}</th>)}</tr></thead>
            <tbody>{out.rows.map((r: any, i: number) => <tr key={i} className="border-t border-slate-100">{out.columns.map((c: string) => <td key={c} className="px-2 py-1">{String(r[c] ?? "NULL")}</td>)}</tr>)}</tbody></table></div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: any }) {
  return <div className="card p-4"><div className="text-xs text-slate-500">{label}</div><div className="mt-1 text-xl font-semibold text-slate-900">{value}</div></div>;
}
