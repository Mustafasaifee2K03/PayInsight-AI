export type Role = "ADMIN" | "ANALYST" | "VIEWER";

export interface User {
  user_id: number;
  email: string;
  full_name: string;
  role: Role;
  permissions: string[];
  allowed_dimensions: string[];
  session_id?: string | null;
}

export type Unit = "count" | "percent" | "currency_minor";
export type CellFormat = Unit | "text" | "pp" | "number" | "bool" | "pct_change" | "count_change";

export interface Kpi {
  metric: string;
  label: string;
  unit: Unit;
  value: number | null;
  formatted?: string;
  numerator?: number | null;
  denominator?: number | null;
  primary?: boolean;
  higher_is_better?: boolean;
  previous?: number | null;
  change_abs?: number | null;
  change_pct?: number | null;
}

export interface Series {
  key: string;
  label: string;
  unit?: string;
  type?: "line" | "bar";
  axis?: "left" | "right";
}

export interface ChartSpec {
  id: string;
  title: string;
  type: "line" | "bar" | "grouped_bar" | "stacked_bar" | "composed" | "band";
  x_key: string;
  series: Series[];
  data: Record<string, any>[];
  unit: string;
  reference_lines?: { y: number; label: string }[];
  reference_areas?: { x1: string; x2: string; label: string }[];
  highlight_key?: string;
}

export interface TableSpec {
  id: string;
  title: string;
  columns: { key: string; label: string; format: CellFormat }[];
  rows: Record<string, any>[];
}

export interface QueryMeta {
  purpose: string;
  sql: string;
  params: Record<string, any>;
  status: string;
  duration_ms: number;
  row_count: number;
  truncated: boolean;
  cached: boolean;
  tables: string[];
  limit_applied: number | null;
  preview?: Record<string, any>[];
  columns?: string[];
}

export interface Recommendation {
  action: string;
  rationale: string;
  priority: "high" | "medium" | "low";
}

export interface QualityWarning {
  check: string;
  affected: number;
  severity: string;
  impact: string;
  treatment: string;
}

export interface MetricDefinition {
  name: string;
  label: string;
  unit: Unit;
  formula: string;
  numerator: string;
  denominator: string | null;
  sql_expression: string;
  notes: string[];
}

export interface AnalysisResult {
  id: string;
  question: string;
  created_at: string;
  status: "completed" | "needs_clarification" | "rejected";
  planner: { engine: string; version: string; external_ai: boolean };
  message?: string;
  suggestions?: string[];
  scenario_id?: string;
  data_profile?: string;
  data_window?: { start: string; end: string };
  summary?: string;
  verdict?: { type: string; label: string; mix_share_pct?: number; dimension?: string; segment?: string } | null;
  interpretation?: {
    intent?: string;
    intent_label?: string;
    metric?: string;
    metric_label?: string;
    dimensions?: { name: string; label: string }[];
    filters?: { dimension: string; values: string[]; labels: string[] }[];
    time_range?: { start: string; end: string; days: number; label: string; explicit: boolean };
    comparison_range?: { start: string; end: string; days: number; label: string } | null;
    assumptions?: string[];
    matched_terms?: { term: string; meaning: string }[];
    confidence?: number;
  };
  plan?: Record<string, any>;
  kpis?: Kpi[];
  charts?: ChartSpec[];
  tables?: TableSpec[];
  facts?: string[];
  hypotheses?: string[];
  recommendations?: Recommendation[];
  caveats?: string[];
  restricted_notes?: string[];
  decomposition?: Record<string, any> | null;
  metric_definitions?: MetricDefinition[];
  datasets?: { table: string; description: string }[];
  queries?: QueryMeta[];
  data_quality?: { status: string; warnings: QualityWarning[]; raw_rows: number; canonical_rows: number };
  execution?: { total_ms: number; query_count: number; cache_hits: number; sql_ms: number; rows_returned: number };
}

export interface HistoryItem {
  analysis_id: string;
  question: string;
  status: string;
  intent: string | null;
  scenario_id: string | null;
  created_at: string;
}

export interface Scenario {
  id: string;
  key: string;
  title: string;
  profile: string;
  description: string;
  suggested_role: Role;
  page: string;
  questions: string[];
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: any };
}

export interface AuthResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface SessionInfo {
  session_id: string;
  created_at: string;
  last_used_at: string;
  expires_at: string;
  user_agent: string | null;
  ip_address: string | null;
  rotation_count: number;
  current: boolean;
}

export interface AdminUser {
  user_id: number;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  locked: boolean;
  created_at: string | null;
  last_login_at: string | null;
  active_sessions: number;
}

export interface AuditEvent {
  event_id: number;
  occurred_at: string;
  event_type: string;
  outcome: "SUCCESS" | "FAILURE";
  user_id: number | null;
  email: string | null;
  session_id: string | null;
  ip_address: string | null;
  detail: any;
}
