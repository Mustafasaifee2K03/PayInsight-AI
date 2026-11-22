import type { AdminUser, AnalysisResult, AuditEvent, AuthResponse, HistoryItem, Scenario, SessionInfo, User } from "../types/api";

/**
 * Auth model (see docs/SECURITY.md):
 * - The short-lived JWT access token lives only in memory (never localStorage), so injected scripts
 *   cannot read it from storage and it disappears when the tab closes.
 * - The refresh token is an httpOnly, SameSite=Strict cookie scoped to /api/auth, invisible to JS.
 * - On a 401 TOKEN_EXPIRED the client silently refreshes once (single-flight) and retries.
 * - On page load, `restoreSession()` exchanges the cookie for a fresh access token.
 */
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: any, public requestId?: string) {
    super(message);
  }
}

const CSRF = { "X-Requested-With": "PayInsight" };
let accessToken: string | null = null;
let refreshing: Promise<AuthResponse | null> | null = null;
let onSessionLost: (() => void) | null = null;

export function setAccessToken(token: string | null) {
  accessToken = token;
}
export function hasAccessToken() {
  return accessToken !== null;
}
/** Called when the session can no longer be renewed (revoked, expired, disabled) so the UI can return to login. */
export function setSessionLostHandler(fn: (() => void) | null) {
  onSessionLost = fn;
}

async function raw(path: string, init: RequestInit = {}, withAuth = true): Promise<Response> {
  const headers: Record<string, string> = { "Content-Type": "application/json", ...CSRF };
  if (withAuth && accessToken) headers.Authorization = `Bearer ${accessToken}`;
  try {
    return await fetch(path, { ...init, credentials: "same-origin", headers: { ...headers, ...(init.headers as any) } });
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the PayInsight backend. Is it running on port 8000?");
  }
}

async function parse<T>(res: Response): Promise<T> {
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const err = body?.error;
    throw new ApiError(res.status, err?.code ?? "HTTP_ERROR", err?.message ?? `Request failed (${res.status})`, err?.details, err?.request_id ?? res.headers.get("X-Request-ID") ?? undefined);
  }
  return body as T;
}

/** Rotate the refresh cookie and obtain a new access token. Concurrent callers share one request. */
export function refreshSession(): Promise<AuthResponse | null> {
  if (!refreshing) {
    refreshing = (async () => {
      for (let attempt = 0; attempt < 2; attempt++) {
        const res = await raw("/api/auth/refresh", { method: "POST" }, false);
        if (res.ok) {
          const data = await parse<AuthResponse>(res);
          accessToken = data.access_token;
          return data;
        }
        const code = (await res.json().catch(() => null))?.error?.code;
        if (code !== "REFRESH_SUPERSEDED") break; // another tab just rotated it: retry once with the new cookie
      }
      accessToken = null;
      return null;
    })().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res = await raw(path, init);
  if (res.status === 401 && accessToken) {
    const code = (await res.clone().json().catch(() => null))?.error?.code;
    if (code === "TOKEN_EXPIRED") {
      const renewed = await refreshSession();
      if (renewed) res = await raw(path, init);
    }
    if (res.status === 401) {
      accessToken = null;
      onSessionLost?.();
    }
  }
  return parse<T>(res);
}

async function authCall(path: string, body: unknown): Promise<AuthResponse> {
  const data = await parse<AuthResponse>(await raw(path, { method: "POST", body: JSON.stringify(body) }, false));
  accessToken = data.access_token;
  return data;
}

export const api = {
  login: (email: string, password: string) => authCall("/api/auth/login", { email, password }),
  signup: (email: string, full_name: string, password: string) => authCall("/api/auth/signup", { email, full_name, password }),
  logout: async () => {
    try {
      await raw("/api/auth/logout", { method: "POST" });
    } finally {
      accessToken = null;
    }
  },
  logoutAll: () => request<{ sessions_revoked: number }>("/api/auth/logout-all", { method: "POST" }),
  me: () => request<User>("/api/auth/me"),
  sessions: () => request<SessionInfo[]>("/api/auth/sessions"),
  revokeSession: (id: string) => request<any>(`/api/auth/sessions/${id}`, { method: "DELETE" }),
  changePassword: (current_password: string, new_password: string) =>
    request<{ other_sessions_revoked: number }>("/api/auth/change-password", { method: "POST", body: JSON.stringify({ current_password, new_password }) }),
  adminUsers: () => request<AdminUser[]>("/api/admin/users"),
  adminUpdateUser: (id: number, patch: { role?: string; is_active?: boolean; unlock?: boolean }) =>
    request<any>(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  adminRevokeSessions: (id: number) => request<{ sessions_revoked: number }>(`/api/admin/users/${id}/revoke-sessions`, { method: "POST" }),
  audit: (limit = 100, eventType?: string) =>
    request<AuditEvent[]>(`/api/admin/audit?limit=${limit}${eventType ? `&event_type=${encodeURIComponent(eventType)}` : ""}`),

  overview: (windowDays: number) => request<any>(`/api/dashboard/overview?window_days=${windowDays}`),
  analyze: (question: string) => request<AnalysisResult>("/api/analytics/analyze", { method: "POST", body: JSON.stringify({ question }) }),
  history: () => request<HistoryItem[]>("/api/analytics/history"),
  result: (id: string) => request<AnalysisResult>(`/api/analytics/result/${id}`),
  scenarios: () => request<{ active: string; data_profile: string; scenarios: Scenario[] }>("/api/scenarios"),
  activate: (scenario_id: string, reseed = false) =>
    request<any>("/api/scenarios/activate", { method: "POST", body: JSON.stringify({ scenario_id, reseed }) }),
  quality: () => request<any>("/api/quality"),
  reconciliation: () => request<any>("/api/reconciliation"),
  datasets: () => request<any>("/api/datasets"),
  validateSql: (sql: string) => request<any>("/api/sql/validate", { method: "POST", body: JSON.stringify({ sql }) }),
  executeSql: (sql: string) => request<any>("/api/sql/execute", { method: "POST", body: JSON.stringify({ sql }) }),
  health: () => request<any>("/health"),
};

/** Password policy mirrored from the backend (backend remains the authority). */
export function passwordChecks(password: string, email: string) {
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  const local = email.split("@")[0]?.toLowerCase() ?? "";
  return [
    { label: "At least 10 characters", ok: password.length >= 10 },
    { label: "3 of: lowercase, uppercase, digit, symbol", ok: classes >= 3 },
    { label: "Does not contain your email name", ok: !(local.length >= 3 && password.toLowerCase().includes(local)) },
  ];
}
