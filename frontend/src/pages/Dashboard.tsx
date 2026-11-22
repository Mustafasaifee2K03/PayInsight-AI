import { useEffect, useState } from "react";
import { CheckCircle2, IndianRupee, Lock, Receipt, XCircle } from "lucide-react";
import { api, ApiError } from "../services/api";
import { ChartCard } from "../components/ChartCard";
import { ErrorBox, KpiCard, Spinner } from "../components/ui";
import type { ChartSpec, Kpi } from "../types/api";
import { formatValue } from "../lib/format";

const ICONS: Record<string, JSX.Element> = {
  transaction_count: <Receipt size={16} />,
  success_rate: <CheckCircle2 size={16} />,
  failed_transactions: <XCircle size={16} />,
  tpv: <IndianRupee size={16} />,
};

export function DashboardPage({ refreshKey }: { refreshKey: number }) {
  const [windowDays, setWindowDays] = useState(30);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    api.overview(windowDays).then(setData).catch(setError);
  }, [windowDays, refreshKey]);

  if (error) return <ErrorBox message={error.message} reference={error.requestId} />;
  if (!data) return <Spinner label="Loading dashboard…" />;

  const kpis: Kpi[] = data.kpis.map((k: any) => ({ ...k, primary: false }));
  const trendSR: ChartSpec = {
    id: "dash_sr", title: "Daily payment success rate (full data window)", type: "composed", x_key: "day", unit: "percent",
    series: [{ key: "success_rate", label: "Success rate" }, { key: "attempts", label: "Attempts" }], data: data.daily_trend,
    reference_areas: [{ x1: data.window.start, x2: data.window.end, label: `KPI window` }],
  };
  const methods: ChartSpec = {
    id: "dash_methods", title: `Payment-method share of attempts (${data.window.label})`, type: "bar", x_key: "segment", unit: "percent",
    series: [{ key: "share_pct", label: "Share of attempts" }], data: data.payment_methods,
  };
  // Failure rate (not success rate) so that zero-based bars still show the real differences.
  const withFR = (rows: any[]) => rows.map((r) => ({ ...r, failure_rate: r.success_rate === null ? null : 100 - r.success_rate }));
  const methodSR: ChartSpec = {
    id: "dash_method_fr", title: `Failure rate by payment method (${data.window.label})`, type: "bar", x_key: "segment", unit: "percent",
    series: [{ key: "failure_rate", label: "Failure rate" }], data: withFR(data.payment_methods),
  };
  const banks: ChartSpec | null = data.banks && {
    id: "dash_banks", title: `Failure rate by bank (${data.window.label})`, type: "bar", x_key: "segment", unit: "percent",
    series: [{ key: "failure_rate", label: "Failure rate" }], data: withFR(data.banks).sort((a: any, b: any) => (b.failure_rate ?? 0) - (a.failure_rate ?? 0)),
  };
  const failures: ChartSpec = {
    id: "dash_fc", title: `Failure-code distribution (${data.window.label})`, type: "bar", x_key: "segment", unit: "count",
    series: [{ key: "failed", label: "Failed transactions" }], data: data.failure_codes,
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Payments overview</h1>
          <p className="text-sm text-slate-500">
            {data.window.start} → {data.window.end}
            {data.previous_window ? ` vs ${data.previous_window.start} → ${data.previous_window.end}` : " (no equal-length previous window available)"} · data profile <code>{data.data_profile}</code>
          </p>
        </div>
        <div className="flex rounded-lg border border-slate-300 bg-white p-0.5 text-sm">
          {[7, 14, 30, 60].map((d) => (
            <button key={d} onClick={() => setWindowDays(d)} className={`rounded-md px-3 py-1 ${windowDays === d ? "bg-navy-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>{d}d</button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {kpis.map((k) => <KpiCard key={k.metric} kpi={k} icon={ICONS[k.metric]} />)}
      </div>
      <ChartCard spec={trendSR} height={300} />
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard spec={methodSR} />
        <ChartCard spec={methods} />
        {banks ? <ChartCard spec={banks} /> : (
          <div className="card flex flex-col items-center justify-center gap-2 p-8 text-center text-sm text-slate-500">
            <Lock size={22} className="text-slate-400" />
            <div className="font-medium text-slate-700">Bank performance is restricted</div>
            <div>Your role does not include bank-level drill-down (enforced by the backend).</div>
          </div>
        )}
        <ChartCard spec={failures} />
      </div>
      <div className="text-xs text-slate-400">
        All figures computed from {data.queries.length} validated read-only SQL queries · success rate = SUCCESS / (SUCCESS + FAILED); PENDING excluded · TPV = successful INR only ·
        {" "}{formatValue(data.queries.reduce((a: number, q: any) => a + q.duration_ms, 0), "number")} ms total SQL time
      </div>
    </div>
  );
}
