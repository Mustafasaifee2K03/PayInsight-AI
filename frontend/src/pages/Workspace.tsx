import { useEffect, useState, type FormEvent } from "react";
import { AlertTriangle, ArrowRight, Clock, Eye, HelpCircle, Lightbulb, ListChecks, Lock, Search, Sparkles, Target } from "lucide-react";
import { api, ApiError } from "../services/api";
import type { AnalysisResult, HistoryItem, Scenario, User } from "../types/api";
import { ChartCard } from "../components/ChartCard";
import { DataTable } from "../components/DataTable";
import { Explainability } from "../components/Explainability";
import { ErrorBox, KpiCard, Spinner } from "../components/ui";

const EXAMPLES: { group: string; qs: string[] }[] = [
  { group: "Basic", qs: ["How many transactions occurred?", "What is the overall success rate?", "What is our total transaction value?", "Show daily transaction trends"] },
  { group: "Intermediate", qs: ["Compare payment success rates by bank", "Which payment methods have the highest failure rates?", "Which merchants have the highest failed transaction volumes?", "What are the main failure codes?", "Compare the last 7 days with the previous 7 days"] },
  { group: "Advanced", qs: ["Why did payment success rate decline?", "Which banks contributed most to the decline?", "Is the decline caused by payment-method mix?", "Which merchants have unusual failure rates?", "Compare bank-level performance across periods"] },
];

const VERDICT_STYLE: Record<string, string> = {
  performance: "bg-red-50 text-red-800 border-red-200",
  mix_shift: "bg-amber-50 text-amber-900 border-amber-200",
  both: "bg-orange-50 text-orange-900 border-orange-200",
  no_material_change: "bg-emerald-50 text-emerald-800 border-emerald-200",
};

export function WorkspacePage({ user, scenario, pending, onPendingConsumed }: { user: User; scenario?: Scenario; pending?: string | null; onPendingConsumed: () => void }) {
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);

  const loadHistory = () => api.history().then(setHistory).catch(() => undefined);
  useEffect(() => { loadHistory(); }, []);

  async function run(q: string) {
    if (!q.trim()) return;
    setQuestion(q);
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.analyze(q));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "UNKNOWN", String(e)));
    } finally {
      setLoading(false);
      loadHistory();
    }
  }

  useEffect(() => {
    if (pending) { run(pending); onPendingConsumed(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending]);

  async function openHistory(id: string) {
    setLoading(true); setError(null);
    try { const r = await api.result(id); setResult(r); setQuestion(r.question); }
    catch (e) { setError(e as ApiError); }
    finally { setLoading(false); }
  }

  const submit = (e: FormEvent) => { e.preventDefault(); run(question); };

  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_280px]">
      <div className="min-w-0 space-y-5">
        <div className="card p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800"><Sparkles size={16} className="text-brand-500" /> Ask a payments question</div>
          <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
            <div className="relative flex-1">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500}
                placeholder="e.g. Why did payment success rate decline?"
                className="w-full rounded-lg border border-slate-300 py-2.5 pl-9 pr-3 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100" />
            </div>
            <button className="btn-primary justify-center px-5" disabled={loading || !question.trim()}>{loading ? "Analysing…" : <>Run analysis <ArrowRight size={15} /></>}</button>
          </form>
          {scenario && (
            <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
              <span className="text-slate-500">Scenario {scenario.id} suggestions:</span>
              {scenario.questions.map((q) => <button key={q} onClick={() => run(q)} className="chip bg-navy-900/5 text-navy-800 hover:bg-navy-900/10">{q}</button>)}
            </div>
          )}
          <details className="mt-2 text-xs">
            <summary className="cursor-pointer text-slate-500 hover:text-slate-700">More example questions</summary>
            <div className="mt-2 grid gap-3 sm:grid-cols-3">
              {EXAMPLES.map((g) => (
                <div key={g.group}>
                  <div className="label mb-1">{g.group}</div>
                  {g.qs.map((q) => <button key={q} onClick={() => run(q)} className="block py-0.5 text-left text-brand-700 hover:underline">{q}</button>)}
                </div>
              ))}
            </div>
          </details>
        </div>

        {loading && <div className="card p-6"><Spinner label="Planning → generating SQL → validating → executing → reasoning…" /></div>}
        {error && <ErrorView error={error} user={user} />}
        {result && result.status !== "completed" && <ClarificationView r={result} onAsk={run} />}
        {result && result.status === "completed" && <ResultView r={result} />}
        {!loading && !error && !result && (
          <div className="card p-8 text-center text-sm text-slate-500">
            Ask a question or pick an example. Every answer shows the plan, the SQL that ran, and the evidence behind it.
          </div>
        )}
      </div>

      <aside className="space-y-4">
        <div className="card">
          <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2.5 text-sm font-semibold text-slate-800"><Clock size={15} /> Query history</div>
          <div className="max-h-[520px] overflow-auto">
            {history.length ? history.map((h) => (
              <button key={h.analysis_id} onClick={() => openHistory(h.analysis_id)} className="block w-full border-b border-slate-50 px-4 py-2 text-left hover:bg-slate-50">
                <div className="line-clamp-2 text-sm text-slate-800">{h.question}</div>
                <div className="mt-0.5 text-[11px] text-slate-400">{h.intent ?? h.status} · scenario {h.scenario_id} · {new Date(h.created_at).toLocaleTimeString()}</div>
              </button>
            )) : <div className="px-4 py-6 text-center text-xs text-slate-400">No analyses yet.</div>}
          </div>
        </div>
      </aside>
    </div>
  );
}

function ErrorView({ error, user }: { error: ApiError; user: User }) {
  if (error.status === 403) {
    return (
      <div className="card border-red-200 p-5">
        <div className="flex gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-red-100"><Lock size={18} className="text-red-700" /></div>
          <div>
            <div className="font-semibold text-red-800">Access denied — HTTP 403 ({error.code})</div>
            <div className="mt-1 text-sm text-slate-700">{error.message}</div>
            {error.details?.restricted_dimensions && (
              <div className="mt-2 text-xs text-slate-500">
                Restricted: <b>{error.details.restricted_dimensions.join(", ")}</b> · Allowed for {user.role}: {error.details.allowed_dimensions?.join(", ")}
              </div>
            )}
            <div className="mt-2 text-xs text-slate-500">Enforced by the backend authorization layer before any SQL was generated or executed.</div>
            {error.requestId && <div className="mt-1 font-mono text-xs text-slate-400">Reference: {error.requestId}</div>}
          </div>
        </div>
      </div>
    );
  }
  return <ErrorBox title={`Analysis failed (${error.code})`} message={error.message} details={error.details?.reasons} reference={error.requestId} />;
}

function ClarificationView({ r, onAsk }: { r: AnalysisResult; onAsk: (q: string) => void }) {
  const rejected = r.status === "rejected";
  return (
    <div className={`card p-5 ${rejected ? "border-red-200" : "border-amber-200"}`}>
      <div className="flex gap-3">
        {rejected ? <AlertTriangle className="shrink-0 text-red-600" size={20} /> : <HelpCircle className="shrink-0 text-amber-600" size={20} />}
        <div>
          <div className="font-semibold text-slate-900">{rejected ? "Request not supported" : "Clarification needed"}</div>
          <div className="mt-1 text-sm text-slate-700">{r.message}</div>
          {!!r.suggestions?.length && (
            <div className="mt-3 flex flex-wrap gap-1.5">
              {r.suggestions.map((s) => <button key={s} onClick={() => onAsk(s)} className="chip bg-brand-50 text-brand-700 hover:bg-brand-100">{s}</button>)}
            </div>
          )}
          <div className="mt-3 text-xs text-slate-400">No SQL was generated — the planner does not guess metrics, denominators or date ranges.</div>
        </div>
      </div>
    </div>
  );
}

function ResultView({ r }: { r: AnalysisResult }) {
  const it = r.interpretation!;
  return (
    <div className="space-y-5">
      <div className="card p-5">
        <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
          <span className="chip bg-navy-900 text-white">{it.intent_label}</span>
          <span>{it.time_range?.start} → {it.time_range?.end}</span>
          {it.comparison_range && <span>vs {it.comparison_range.start} → {it.comparison_range.end}</span>}
          <span>· {r.execution?.query_count} SQL queries · {r.execution?.total_ms} ms</span>
        </div>
        <p className="mt-3 text-[15px] leading-relaxed text-slate-900">{r.summary}</p>
        {r.verdict && (
          <div className={`mt-3 inline-flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-medium ${VERDICT_STYLE[r.verdict.type] ?? "bg-slate-50"}`}>
            <Target size={15} /> Verdict: {r.verdict.label}
            {r.verdict.mix_share_pct !== undefined && r.verdict.type !== "no_material_change" && <span className="font-normal opacity-80">(mix ≈ {r.verdict.mix_share_pct.toFixed(0)}% of change)</span>}
          </div>
        )}
        {!!it.assumptions?.length && (
          <div className="mt-3 text-xs text-amber-800"><b>Assumptions:</b> {it.assumptions.join(" ")}</div>
        )}
        {!!r.restricted_notes?.length && <div className="mt-2 flex items-center gap-1.5 text-xs text-slate-600"><Lock size={12} /> {r.restricted_notes.join(" ")}</div>}
      </div>

      {!!r.kpis?.length && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-6">
          {r.kpis.map((k) => <KpiCard key={k.metric + k.label} kpi={k} />)}
        </div>
      )}

      {!!r.charts?.length && (
        <div className="grid gap-4 lg:grid-cols-2">
          {r.charts.map((c, i) => <div key={c.id} className={r.charts!.length % 2 === 1 && i === 0 ? "lg:col-span-2" : ""}><ChartCard spec={c} /></div>)}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="card p-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-navy-800"><Eye size={14} /> Observed facts</div>
          <ul className="space-y-1.5 text-sm text-slate-700">{r.facts?.map((f, i) => <li key={i} className="border-l-2 border-brand-300 pl-2">{f}</li>)}</ul>
        </div>
        <div className="card p-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-amber-800"><Lightbulb size={14} /> Potential explanations / hypotheses</div>
          {r.hypotheses?.length ? <ul className="space-y-1.5 text-sm text-slate-700">{r.hypotheses.map((h, i) => <li key={i} className="border-l-2 border-amber-300 pl-2">{h}</li>)}</ul>
            : <div className="text-sm text-slate-400">No hypotheses — the evidence does not suggest a specific explanation.</div>}
          <div className="mt-2 text-[11px] text-slate-400">Hypotheses are correlational; they are not proven causes.</div>
        </div>
        <div className="card p-4">
          <div className="mb-2 flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-emerald-800"><ListChecks size={14} /> Recommended actions</div>
          {r.recommendations?.length ? (
            <ul className="space-y-2 text-sm">{r.recommendations.map((x, i) => (
              <li key={i}>
                <div className="flex items-start gap-1.5"><span className={`chip mt-0.5 shrink-0 ${x.priority === "high" ? "bg-red-50 text-red-700" : x.priority === "medium" ? "bg-amber-50 text-amber-800" : "bg-slate-100 text-slate-600"}`}>{x.priority}</span><span className="font-medium text-slate-800">{x.action}</span></div>
                <div className="ml-1 mt-0.5 text-xs text-slate-500">{x.rationale}</div>
              </li>))}</ul>
          ) : <div className="text-sm text-slate-400">No specific actions recommended.</div>}
        </div>
      </div>

      {!!r.caveats?.length && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600">
          <b>Caveats:</b> <ul className="mt-1 list-disc pl-4">{r.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
        </div>
      )}

      {r.tables?.map((t) => <DataTable key={t.id} table={t} />)}

      <Explainability r={r} />
    </div>
  );
}
