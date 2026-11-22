import { Download } from "lucide-react";
import type { TableSpec } from "../types/api";
import { downloadCSV, formatValue, toCSV } from "../lib/format";

function cellClass(fmt: string, v: any): string {
  if ((fmt === "pp" || fmt === "pct_change" || fmt === "count_change") && typeof v === "number") {
    if (v < -0.005) return "text-red-700";
    if (v > 0.005) return "text-emerald-700";
  }
  if (fmt === "bool" && v === true) return "font-semibold text-red-700";
  return "";
}

export function DataTable({ table, maxRows = 50 }: { table: TableSpec; maxRows?: number }) {
  const rows = table.rows.slice(0, maxRows);
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
        <h3 className="text-sm font-semibold text-slate-800">{table.title}</h3>
        <button className="btn-ghost !px-2 !py-1 text-xs" onClick={() => downloadCSV(`${table.id}.csv`, toCSV(table.columns, table.rows))} title="Export CSV">
          <Download size={14} /> CSV
        </button>
      </div>
      <div className="max-h-[420px] overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-slate-50 text-left">
            <tr>
              {table.columns.map((c) => (
                <th key={c.key} className={`whitespace-nowrap px-3 py-2 text-xs font-semibold text-slate-500 ${c.format === "text" ? "" : "text-right"}`}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-slate-100 hover:bg-slate-50/70">
                {table.columns.map((c) => (
                  <td key={c.key} className={`whitespace-nowrap px-3 py-1.5 ${c.format === "text" ? "text-slate-800" : "text-right tabular-nums"} ${cellClass(c.format, r[c.key])}`}>
                    {formatValue(r[c.key], c.format)}
                    {c.key === "segment" && r.low_sample && <span className="chip ml-2 bg-amber-50 text-amber-700">low sample</span>}
                  </td>
                ))}
              </tr>
            ))}
            {!rows.length && (
              <tr><td colSpan={table.columns.length} className="px-3 py-6 text-center text-slate-400">No rows.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {table.rows.length > maxRows && <div className="border-t border-slate-100 px-4 py-1.5 text-xs text-slate-500">Showing {maxRows} of {table.rows.length} rows — CSV contains all rows.</div>}
    </div>
  );
}
