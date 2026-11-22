import { useState } from "react";
import { CheckCircle2, Play, RefreshCw, UserRound } from "lucide-react";
import type { Scenario, User } from "../types/api";

export function ScenariosPage(props: {
  user: User;
  scenarios: Scenario[];
  active: string;
  switching: boolean;
  onActivate: (id: string, reseed?: boolean) => Promise<void>;
  onAsk: (q: string) => void;
  onOpenQuality: () => void;
}) {
  const canSwitch = props.user.permissions.includes("scenarios:activate");
  const [msg, setMsg] = useState<string | null>(null);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-slate-900">Demo scenarios</h1>
          <p className="text-sm text-slate-500">Deterministic, seeded datasets (seed 20250901, fixed window 2025-09-01 → 2025-10-30). Switching never requires editing code or data.</p>
        </div>
        {canSwitch && (
          <button className="btn-outline" disabled={props.switching} onClick={async () => { await props.onActivate(props.active, true); setMsg("Active scenario reseeded from its deterministic generator; cache cleared."); }}>
            <RefreshCw size={15} /> Reset / reseed active scenario
          </button>
        )}
      </div>
      {msg && <div className="rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-800">{msg}</div>}
      {!canSwitch && <div className="rounded-lg bg-slate-100 px-4 py-2 text-sm text-slate-600">Scenario activation is an administrative operation (ADMIN only). You can still run the suggested questions on the active scenario.</div>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {props.scenarios.map((s) => {
          const isActive = s.id === props.active;
          return (
            <div key={s.id} className={`card flex flex-col p-4 ${isActive ? "ring-2 ring-brand-500" : ""}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-navy-900 text-sm font-bold text-white">{s.id}</span>
                  <div className="font-semibold text-slate-900">{s.title}</div>
                </div>
                {isActive && <span className="chip bg-brand-50 text-brand-700"><CheckCircle2 size={12} /> active</span>}
              </div>
              <p className="mt-2 flex-1 text-sm text-slate-600">{s.description}</p>
              <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
                <span className="chip bg-slate-100">profile: {s.profile}</span>
                <span className="chip bg-slate-100"><UserRound size={11} /> best as {s.suggested_role}</span>
              </div>
              <div className="mt-3 space-y-1">
                {s.questions.map((q) => (
                  <button key={q} disabled={!isActive} onClick={() => props.onAsk(q)} className="block w-full truncate rounded-md px-2 py-1 text-left text-xs text-brand-700 hover:bg-brand-50 disabled:text-slate-400 disabled:hover:bg-transparent" title={isActive ? "Run in workspace" : "Activate this scenario first"}>
                    → {q}
                  </button>
                ))}
              </div>
              <div className="mt-3 flex gap-2">
                {canSwitch && !isActive && <button className="btn-primary !py-1.5 text-xs" disabled={props.switching} onClick={() => props.onActivate(s.id)}><Play size={13} /> Activate</button>}
                {isActive && s.page === "quality" && props.user.permissions.includes("quality") && <button className="btn-outline !py-1.5 text-xs" onClick={props.onOpenQuality}>Open data quality & sources</button>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
