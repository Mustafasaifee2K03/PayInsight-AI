import { useCallback, useEffect, useState } from "react";
import { api, ApiError, refreshSession, setSessionLostHandler } from "./services/api";
import type { Scenario, User } from "./types/api";
import { Layout, type Page } from "./components/Layout";
import { LoginPage } from "./pages/Login";
import { DashboardPage } from "./pages/Dashboard";
import { WorkspacePage } from "./pages/Workspace";
import { DataQualityPage } from "./pages/DataQuality";
import { ScenariosPage } from "./pages/Scenarios";
import { AccountPage } from "./pages/Account";
import { UsersPage } from "./pages/Users";
import { ErrorBox, Spinner } from "./components/ui";

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);
  const [sessionNote, setSessionNote] = useState<string | null>(null);
  const [page, setPage] = useState<Page>("dashboard");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [active, setActive] = useState("A");
  const [switching, setSwitching] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [pending, setPending] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  // Restore the session from the httpOnly refresh cookie on page load (access token lives in memory only).
  useEffect(() => {
    refreshSession().then((r) => setUser(r ? r.user : null)).catch(() => setUser(null)).finally(() => setBooting(false));
  }, []);

  // If the server revokes the session (sign-out elsewhere, disabled account, token reuse), return to login.
  useEffect(() => {
    setSessionLostHandler(() => {
      setUser(null);
      setSessionNote("Your session ended (signed out, revoked or expired). Please sign in again.");
    });
    return () => setSessionLostHandler(null);
  }, []);

  const loadScenarios = useCallback(() => {
    api.scenarios().then((s) => { setScenarios(s.scenarios); setActive(s.active); }).catch(() => undefined);
  }, []);
  useEffect(() => { if (user) loadScenarios(); }, [user, loadScenarios]);

  async function activate(id: string, reseed = false) {
    setSwitching(true);
    setBanner(null);
    try {
      const r = await api.activate(id, reseed);
      setActive(r.active);
      setRefreshKey((k) => k + 1);
      setBanner(`Scenario ${r.active} active (data profile “${r.data_profile}”)${r.regenerated ? `, generated in ${r.generation_seconds}s` : ""}. Cache invalidated.`);
    } catch (e) {
      setBanner(e instanceof ApiError ? `Could not switch scenario: ${e.message}` : "Could not switch scenario");
    } finally {
      setSwitching(false);
    }
  }

  async function logout() {
    try { await api.logout(); } catch { /* ignore */ }
    setUser(null);
    setPage("dashboard");
  }

  if (booting) return <div className="p-10"><Spinner label="Restoring session…" /></div>;
  if (!user) return (
    <>
      {sessionNote && <div className="fixed inset-x-0 top-0 z-20 bg-amber-50 px-4 py-2 text-center text-sm text-amber-900">{sessionNote}</div>}
      <LoginPage onLogin={(u) => { setUser(u); setSessionNote(null); setPage("dashboard"); }} />
    </>
  );

  const scenario = scenarios.find((s) => s.id === active);
  return (
    <Layout user={user} page={page} onNavigate={setPage} onLogout={logout} scenarios={scenarios} activeScenario={active} onActivate={(id) => activate(id)} switching={switching}>
      {banner && <div className="mb-4 rounded-lg border border-brand-100 bg-brand-50 px-4 py-2 text-sm text-brand-700">{banner}</div>}
      {page === "dashboard" && <DashboardPage refreshKey={refreshKey} />}
      {page === "workspace" && <WorkspacePage key={refreshKey} user={user} scenario={scenario} pending={pending} onPendingConsumed={() => setPending(null)} />}
      {page === "quality" && <DataQualityPage user={user} refreshKey={refreshKey} />}
      {page === "scenarios" && (
        <ScenariosPage user={user} scenarios={scenarios} active={active} switching={switching} onActivate={activate}
          onAsk={(q) => { setPending(q); setPage("workspace"); }} onOpenQuality={() => setPage("quality")} />
      )}
      {page === "account" && <AccountPage user={user} onSignedOut={() => { setUser(null); setSessionNote("Signed out of all sessions."); }} />}
      {page === "users" && (user.permissions.includes("users:manage") ? <UsersPage me={user} /> : <ErrorBox title="Access denied" message="User administration requires the ADMIN role." />)}
      {!["dashboard", "workspace", "quality", "scenarios", "account", "users"].includes(page) && <ErrorBox message="Unknown page" />}
    </Layout>
  );
}
