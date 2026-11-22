import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Check, KeyRound, LogOut, Monitor, ShieldCheck, X } from "lucide-react";
import { api, ApiError, passwordChecks } from "../services/api";
import type { SessionInfo, User } from "../types/api";
import { ErrorBox, Spinner } from "../components/ui";
import { describeUserAgent, formatDateTime } from "../lib/format";

const INPUT = "mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100";

export function AccountPage({ user, onSignedOut }: { user: User; onSignedOut: () => void }) {
  const [sessions, setSessions] = useState<SessionInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    api.sessions().then(setSessions).catch((e) => setError(e instanceof ApiError ? e.message : "Could not load sessions"));
  }, []);
  useEffect(load, [load]);

  async function revoke(id: string) {
    await api.revokeSession(id);
    setNotice("Session revoked. That device must sign in again.");
    load();
  }

  async function logoutEverywhere() {
    const r = await api.logoutAll();
    setNotice(`Signed out of ${r.sessions_revoked} session(s).`);
    onSignedOut();
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Account &amp; Security</h1>
        <p className="text-sm text-slate-500">Your profile, active sessions and password.</p>
      </div>
      {notice && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">{notice}</div>}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="card p-5">
          <div className="label">Profile</div>
          <div className="mt-3 text-lg font-semibold text-slate-900">{user.full_name}</div>
          <div className="text-sm text-slate-500">{user.email}</div>
          <div className="mt-4 label">Role</div>
          <div className="mt-1 text-sm font-medium text-slate-800">{user.role}</div>
          <div className="mt-4 label">Permissions</div>
          <div className="mt-1 flex flex-wrap gap-1.5">{user.permissions.map((p) => <span key={p} className="chip bg-slate-100 text-slate-700">{p}</span>)}</div>
          <div className="mt-4 label">Analysable dimensions</div>
          <div className="mt-1 flex flex-wrap gap-1.5">{user.allowed_dimensions.map((d) => <span key={d} className="chip bg-brand-50 text-brand-700">{d}</span>)}</div>
        </div>

        <div className="card p-5 lg:col-span-2">
          <div className="flex items-center justify-between">
            <div className="label flex items-center gap-1.5"><Monitor size={13} /> Active sessions</div>
            <button className="btn-outline !py-1.5 text-xs" onClick={logoutEverywhere} data-testid="logout-all"><LogOut size={14} /> Sign out everywhere</button>
          </div>
          {error && <div className="mt-3"><ErrorBox message={error} /></div>}
          {!sessions && !error && <div className="mt-3"><Spinner /></div>}
          {sessions && (
            <table className="mt-3 w-full text-sm" data-testid="sessions-table">
              <thead><tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="py-2 font-medium">Device</th><th className="font-medium">IP</th><th className="font-medium">Signed in</th>
                <th className="font-medium">Last active</th><th className="font-medium">Token rotations</th><th />
              </tr></thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.session_id} className="border-b border-slate-100 last:border-0">
                    <td className="py-2.5">
                      <span className="font-medium text-slate-800">{describeUserAgent(s.user_agent)}</span>
                      {s.current && <span className="chip ml-2 bg-emerald-50 text-emerald-700">This device</span>}
                    </td>
                    <td className="text-slate-600">{s.ip_address ?? "—"}</td>
                    <td className="text-slate-600">{formatDateTime(s.created_at)}</td>
                    <td className="text-slate-600">{formatDateTime(s.last_used_at)}</td>
                    <td className="tabular-nums text-slate-600">{s.rotation_count}</td>
                    <td className="text-right">{!s.current && <button className="btn-ghost !px-2 !py-1 text-xs text-red-600" onClick={() => revoke(s.session_id)}>Revoke</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="mt-3 text-xs text-slate-500">
            Each sign-in creates a server-side session. Access tokens expire after 15 minutes and are renewed with a refresh token that rotates every time;
            replaying an old refresh token revokes the session.
          </p>
        </div>
      </div>

      <ChangePassword user={user} onChanged={(n) => { setNotice(`Password changed. ${n} other session(s) were signed out.`); load(); }} />
    </div>
  );
}

function ChangePassword({ user, onChanged }: { user: User; onChanged: (revoked: number) => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<{ message: string; problems?: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const checks = passwordChecks(next, user.email);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      onChanged(r.other_sessions_revoked);
    } catch (err) {
      setError(err instanceof ApiError ? { message: err.message, problems: err.details?.problems } : { message: "Failed" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card max-w-xl p-5">
      <div className="label flex items-center gap-1.5"><KeyRound size={13} /> Change password</div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div><label className="label" htmlFor="cur">Current password</label>
          <input id="cur" type="password" className={INPUT} value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" /></div>
        <div><label className="label" htmlFor="new">New password</label>
          <input id="new" type="password" className={INPUT} value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" /></div>
      </div>
      <ul className="mt-2 space-y-1 text-xs">
        {checks.map((c) => <li key={c.label} className={`flex items-center gap-1.5 ${c.ok ? "text-emerald-700" : "text-slate-500"}`}>{c.ok ? <Check size={13} /> : <X size={13} />} {c.label}</li>)}
      </ul>
      {error && (
        <div className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error.message}{error.problems && <ul className="mt-1 list-disc pl-5">{error.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
        </div>
      )}
      <button className="btn-primary mt-4" disabled={busy || !current || !checks.every((c) => c.ok)}><ShieldCheck size={15} /> Update password</button>
      <p className="mt-2 text-xs text-slate-500">Changing your password signs out every other device.</p>
    </form>
  );
}
