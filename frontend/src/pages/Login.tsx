import { useState, type FormEvent } from "react";
import { Activity, Check, KeyRound, Lock, ShieldCheck, UserPlus, X } from "lucide-react";
import { api, ApiError, passwordChecks } from "../services/api";
import type { User } from "../types/api";

const DEMO = [
  { email: "admin@payinsight.demo", role: "ADMIN", desc: "Full analytics, data quality, scenarios, SQL sandbox, user admin" },
  { email: "analyst@payinsight.demo", role: "ANALYST", desc: "All analysis dimensions incl. bank & merchant" },
  { email: "viewer@payinsight.demo", role: "VIEWER", desc: "Aggregate summaries only — no bank/merchant drill-down" },
];
const DEMO_PASSWORD = "PayInsight@2026";
const INPUT = "mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100";

export function LoginPage({ onLogin }: { onLogin: (u: User) => void }) {
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("admin@payinsight.demo");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<{ message: string; problems?: string[] } | null>(null);
  const [busy, setBusy] = useState(false);

  const checks = passwordChecks(password, email);
  const signupReady = mode === "signup" && checks.every((c) => c.ok) && fullName.trim().length >= 2;

  function switchMode(m: "signin" | "signup") {
    setMode(m);
    setError(null);
    setPassword("");
    if (m === "signup") setEmail("");
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = mode === "signin" ? await api.login(email, password) : await api.signup(email, fullName, password);
      onLogin(res.user);
    } catch (err) {
      if (err instanceof ApiError) setError({ message: err.message, problems: err.details?.problems });
      else setError({ message: "Request failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-navy-900 p-12 text-white lg:flex">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-brand-500"><Activity size={22} /></div>
          <div>
            <div className="text-lg font-semibold">PayInsight AI</div>
            <div className="text-xs text-slate-400">Enterprise Payments Intelligence</div>
          </div>
        </div>
        <div className="max-w-md">
          <h1 className="text-3xl font-semibold leading-tight">Ask why payments are failing. Get evidence, not guesses.</h1>
          <p className="mt-4 text-slate-300">
            Natural-language questions become validated analysis plans, safe SQL, period comparisons and mix decompositions —
            every number traceable to an executed query.
          </p>
          <ul className="mt-6 space-y-2 text-sm text-slate-300">
            <li className="flex gap-2"><ShieldCheck size={16} className="text-brand-300" /> JWT access tokens + rotating refresh sessions</li>
            <li className="flex gap-2"><ShieldCheck size={16} className="text-brand-300" /> Role-based access enforced in the backend</li>
            <li className="flex gap-2"><ShieldCheck size={16} className="text-brand-300" /> Read-only, allowlisted, validated SQL</li>
            <li className="flex gap-2"><ShieldCheck size={16} className="text-brand-300" /> Local deterministic analysis engine — No external AI API</li>
          </ul>
        </div>
        <div className="text-xs text-slate-500">Synthetic demo data only. No real customer or cardholder information.</div>
      </div>

      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-md">
          <div className="mb-6 grid grid-cols-2 rounded-lg bg-slate-100 p-1 text-sm">
            {(["signin", "signup"] as const).map((m) => (
              <button key={m} type="button" onClick={() => switchMode(m)} data-testid={`tab-${m}`}
                className={`rounded-md py-1.5 font-medium transition ${mode === m ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}>
                {m === "signin" ? "Sign in" : "Create account"}
              </button>
            ))}
          </div>
          <h2 className="text-2xl font-semibold text-slate-900">{mode === "signin" ? "Sign in" : "Create your account"}</h2>
          <p className="mt-1 text-sm text-slate-500">
            {mode === "signin" ? "Use your account or one of the demo accounts below." : "New accounts start with the Viewer role. An admin can grant more access."}
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            {mode === "signup" && (
              <div>
                <label className="label" htmlFor="full_name">Full name</label>
                <input id="full_name" className={INPUT} value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" />
              </div>
            )}
            <div>
              <label className="label" htmlFor="email">Email</label>
              <input id="email" type="email" className={INPUT} value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
            </div>
            <div>
              <label className="label" htmlFor="password">Password</label>
              <input id="password" type="password" className={INPUT} value={password} onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "signin" ? "current-password" : "new-password"} placeholder={mode === "signin" ? "Password" : "Choose a strong password"} required />
              {mode === "signup" && (
                <ul className="mt-2 space-y-1 text-xs" aria-label="Password requirements">
                  {checks.map((c) => (
                    <li key={c.label} className={`flex items-center gap-1.5 ${c.ok ? "text-emerald-700" : "text-slate-500"}`}>
                      {c.ok ? <Check size={13} /> : <X size={13} />} {c.label}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {error && (
              <div className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                {error.message}
                {error.problems && <ul className="mt-1 list-disc pl-5">{error.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
              </div>
            )}
            <button type="submit" disabled={busy || (mode === "signup" && !signupReady)} className="btn-primary w-full justify-center py-2.5">
              {mode === "signin" ? <Lock size={15} /> : <UserPlus size={15} />}
              {busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Create account"}
            </button>
          </form>

          {mode === "signin" && (
            <div className="mt-8">
              <div className="label">Demo accounts — password <code className="rounded bg-slate-100 px-1.5 py-0.5 normal-case text-slate-700">{DEMO_PASSWORD}</code></div>
              <div className="mt-2 space-y-2">
                {DEMO.map((d) => (
                  <button key={d.email} type="button" onClick={() => { setEmail(d.email); setPassword(DEMO_PASSWORD); }}
                    className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition hover:border-brand-300 hover:bg-brand-50 ${email === d.email ? "border-brand-300 bg-brand-50" : "border-slate-200"}`}>
                    <div className="flex items-center justify-between"><span className="font-medium text-slate-800">{d.email}</span><span className="chip bg-slate-100 text-slate-600">{d.role}</span></div>
                    <div className="text-xs text-slate-500">{d.desc}</div>
                  </button>
                ))}
              </div>
            </div>
          )}
          <p className="mt-6 flex items-center gap-1.5 text-xs text-slate-400">
            <KeyRound size={12} /> 15-min JWT access token in memory · rotating refresh token in an httpOnly cookie · lockout after 5 failed attempts
          </p>
        </div>
      </div>
    </div>
  );
}
