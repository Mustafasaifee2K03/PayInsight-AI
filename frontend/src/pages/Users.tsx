import { useCallback, useEffect, useState } from "react";
import { Ban, CheckCircle2, LockOpen, LogOut, ScrollText, Users as UsersIcon } from "lucide-react";
import { api, ApiError } from "../services/api";
import type { AdminUser, AuditEvent, Role, User } from "../types/api";
import { ErrorBox, Spinner } from "../components/ui";
import { formatDateTime } from "../lib/format";

const ROLES: Role[] = ["ADMIN", "ANALYST", "VIEWER"];
const EVENT_TYPES = ["", "LOGIN", "SIGNUP", "TOKEN_REFRESH", "LOGOUT", "ACCOUNT_LOCKED", "REFRESH_TOKEN_REUSE", "USER_UPDATED", "PASSWORD_CHANGE", "SESSION_REVOKED", "SESSIONS_REVOKED"];

export function UsersPage({ me }: { me: User }) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [eventType, setEventType] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadUsers = useCallback(() => {
    api.adminUsers().then(setUsers).catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load users"));
  }, []);
  const loadAudit = useCallback(() => {
    api.audit(100, eventType || undefined).then(setEvents).catch((e) => setError(e instanceof ApiError ? e.message : "Failed to load audit log"));
  }, [eventType]);
  useEffect(loadUsers, [loadUsers]);
  useEffect(loadAudit, [loadAudit]);

  async function update(u: AdminUser, patch: { role?: Role; is_active?: boolean; unlock?: boolean }, msg: string) {
    setError(null);
    try {
      await api.adminUpdateUser(u.user_id, patch);
      setNotice(msg);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Update failed");
    }
    loadUsers();
    loadAudit();
  }

  async function revokeAll(u: AdminUser) {
    const r = await api.adminRevokeSessions(u.user_id);
    setNotice(`Revoked ${r.sessions_revoked} session(s) for ${u.email}.`);
    loadUsers();
    loadAudit();
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Users &amp; Audit</h1>
        <p className="text-sm text-slate-500">Role assignments take effect on the user's very next request: roles are read from the database, not trusted from the token.</p>
      </div>
      {notice && <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">{notice}</div>}
      {error && <ErrorBox message={error} />}

      <div className="card p-5">
        <div className="label flex items-center gap-1.5"><UsersIcon size={13} /> Users</div>
        {!users ? <div className="mt-3"><Spinner /></div> : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm" data-testid="users-table">
              <thead><tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="py-2 font-medium">User</th><th className="font-medium">Role</th><th className="font-medium">Status</th>
                <th className="font-medium">Sessions</th><th className="font-medium">Last sign-in</th><th className="font-medium">Created</th><th />
              </tr></thead>
              <tbody>
                {users.map((u) => {
                  const self = u.user_id === me.user_id;
                  return (
                    <tr key={u.user_id} className="border-b border-slate-100 last:border-0" data-email={u.email}>
                      <td className="py-2.5"><div className="font-medium text-slate-800">{u.full_name}{self && <span className="ml-1 text-xs text-slate-400">(you)</span>}</div><div className="text-xs text-slate-500">{u.email}</div></td>
                      <td>
                        <select aria-label={`Role for ${u.email}`} disabled={self} value={u.role}
                          onChange={(e) => update(u, { role: e.target.value as Role }, `${u.email} is now ${e.target.value}.`)}
                          className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm disabled:bg-slate-50">
                          {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                        </select>
                      </td>
                      <td>
                        {!u.is_active ? <span className="chip bg-red-50 text-red-700">Disabled</span>
                          : u.locked ? <span className="chip bg-amber-50 text-amber-800">Locked</span>
                          : <span className="chip bg-emerald-50 text-emerald-700">Active</span>}
                      </td>
                      <td className="tabular-nums text-slate-600">{u.active_sessions}</td>
                      <td className="text-slate-600">{formatDateTime(u.last_login_at)}</td>
                      <td className="text-slate-600">{formatDateTime(u.created_at)}</td>
                      <td className="whitespace-nowrap text-right">
                        {u.locked && <button className="btn-ghost !px-2 !py-1 text-xs" title="Unlock" onClick={() => update(u, { unlock: true }, `${u.email} unlocked.`)}><LockOpen size={14} /> Unlock</button>}
                        {!self && u.active_sessions > 0 && <button className="btn-ghost !px-2 !py-1 text-xs" title="Sign out all sessions" onClick={() => revokeAll(u)}><LogOut size={14} /></button>}
                        {!self && (u.is_active
                          ? <button className="btn-ghost !px-2 !py-1 text-xs text-red-600" onClick={() => update(u, { is_active: false }, `${u.email} disabled and signed out.`)}><Ban size={14} /> Disable</button>
                          : <button className="btn-ghost !px-2 !py-1 text-xs text-emerald-700" onClick={() => update(u, { is_active: true }, `${u.email} re-enabled.`)}><CheckCircle2 size={14} /> Enable</button>)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="label flex items-center gap-1.5"><ScrollText size={13} /> Security audit log (latest 100)</div>
          <select aria-label="Filter events" value={eventType} onChange={(e) => setEventType(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-sm">
            {EVENT_TYPES.map((t) => <option key={t} value={t}>{t || "All events"}</option>)}
          </select>
        </div>
        {!events ? <div className="mt-3"><Spinner /></div> : (
          <div className="mt-3 max-h-[420px] overflow-auto">
            <table className="w-full text-sm" data-testid="audit-table">
              <thead className="sticky top-0 bg-white"><tr className="border-b border-slate-200 text-left text-xs text-slate-500">
                <th className="py-2 font-medium">Time</th><th className="font-medium">Event</th><th className="font-medium">Outcome</th>
                <th className="font-medium">User</th><th className="font-medium">IP</th><th className="font-medium">Detail</th>
              </tr></thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.event_id} className="border-b border-slate-100 last:border-0 align-top">
                    <td className="whitespace-nowrap py-2 text-slate-600">{formatDateTime(e.occurred_at)}</td>
                    <td className="font-mono text-xs text-slate-800">{e.event_type}</td>
                    <td><span className={`chip ${e.outcome === "SUCCESS" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>{e.outcome}</span></td>
                    <td className="text-slate-600">{e.email ?? (e.user_id ? `#${e.user_id}` : "—")}</td>
                    <td className="text-slate-600">{e.ip_address ?? "—"}</td>
                    <td className="max-w-[320px] truncate text-xs text-slate-500" title={typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail)}>
                      {e.detail == null ? "" : typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
