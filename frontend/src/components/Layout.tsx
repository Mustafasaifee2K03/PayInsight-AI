import type { ReactNode } from "react";
import { Activity, Cpu, Database, FlaskConical, LayoutDashboard, LogOut, ShieldCheck, Sparkles, UserCog } from "lucide-react";
import type { Scenario, User } from "../types/api";

export type Page = "dashboard" | "workspace" | "quality" | "scenarios" | "account" | "users";

const NAV: { id: Page; label: string; icon: ReactNode; perm?: string }[] = [
  { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={17} /> },
  { id: "workspace", label: "Analytics Workspace", icon: <Sparkles size={17} /> },
  { id: "quality", label: "Data Quality & Sources", icon: <Database size={17} />, perm: "quality" },
  { id: "scenarios", label: "Demo Scenarios", icon: <FlaskConical size={17} /> },
  { id: "users", label: "Users & Audit", icon: <UserCog size={17} />, perm: "users:manage" },
  { id: "account", label: "Account & Security", icon: <ShieldCheck size={17} /> },
];

const ROLE_STYLE: Record<string, string> = {
  ADMIN: "bg-purple-100 text-purple-800",
  ANALYST: "bg-brand-100 text-brand-700",
  VIEWER: "bg-slate-200 text-slate-700",
};

export function Layout(props: {
  user: User;
  page: Page;
  onNavigate: (p: Page) => void;
  onLogout: () => void;
  scenarios: Scenario[];
  activeScenario: string;
  onActivate: (id: string) => void;
  switching: boolean;
  children: ReactNode;
}) {
  const { user, page, scenarios, activeScenario } = props;
  const canSwitch = user.permissions.includes("scenarios:activate");
  const active = scenarios.find((s) => s.id === activeScenario);
  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col bg-navy-900 text-slate-200 md:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-500"><Activity size={20} className="text-white" /></div>
          <div>
            <div className="text-[15px] font-semibold text-white">PayInsight AI</div>
            <div className="text-[11px] text-slate-400">Enterprise Payments Intelligence</div>
          </div>
        </div>
        <nav className="mt-2 flex-1 space-y-0.5 px-3">
          {NAV.map((n) => {
            const locked = n.perm && !user.permissions.includes(n.perm);
            return (
              <button key={n.id} onClick={() => props.onNavigate(n.id)}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${page === n.id ? "bg-navy-700 text-white" : "text-slate-300 hover:bg-navy-800"}`}>
                {n.icon}
                <span className="flex-1 text-left">{n.label}</span>
                {locked && <span className="text-[10px] text-slate-500">ADMIN</span>}
              </button>
            );
          })}
        </nav>
        <div className="m-3 rounded-lg bg-navy-800 p-3 text-[11px] leading-snug text-slate-300">
          <div className="mb-1 flex items-center gap-1.5 font-semibold text-slate-100"><Cpu size={13} /> Analysis engine</div>
          Local deterministic analysis engine — No external AI API.
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white/95 px-4 py-2.5 backdrop-blur md:px-6">
          <div className="md:hidden">
            <select className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm" value={page} onChange={(e) => props.onNavigate(e.target.value as Page)}>
              {NAV.map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}
            </select>
          </div>
          <div className="flex min-w-0 flex-1 items-center gap-2 text-sm">
            <FlaskConical size={16} className="shrink-0 text-slate-400" />
            <span className="hidden text-slate-500 sm:inline">Scenario</span>
            {canSwitch ? (
              <select disabled={props.switching} className="max-w-[260px] rounded-lg border border-slate-300 bg-white px-2 py-1.5 text-sm" value={activeScenario}
                onChange={(e) => props.onActivate(e.target.value)}>
                {scenarios.map((s) => <option key={s.id} value={s.id}>{s.id} — {s.title}</option>)}
              </select>
            ) : (
              <span className="truncate font-medium text-slate-800">{active ? `${active.id} — ${active.title}` : activeScenario}</span>
            )}
            {props.switching && <span className="text-xs text-slate-500">switching…</span>}
          </div>
          <div className="flex items-center gap-3">
            <button className="text-right leading-tight hover:opacity-80" onClick={() => props.onNavigate("account")} title="Account & Security">
              <div className="text-sm font-medium text-slate-800">{user.full_name}</div>
              <div className="text-[11px] text-slate-500">{user.email}</div>
            </button>
            <span className={`chip ${ROLE_STYLE[user.role]}`}>{user.role}</span>
            <button className="btn-ghost !p-2" onClick={props.onLogout} title="Sign out"><LogOut size={16} /></button>
          </div>
        </header>
        <main className="flex-1 px-4 py-5 md:px-6">{props.children}</main>
      </div>
    </div>
  );
}
