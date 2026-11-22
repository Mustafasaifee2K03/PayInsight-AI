import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec } from "../types/api";
import { CURRENT_COLOR, PREVIOUS_COLOR, SERIES_COLORS, formatTick, formatValue, shortDay } from "../lib/format";

const AXIS = { stroke: "#c3c2b7", tick: { fill: "#64748b", fontSize: 11 }, tickLine: false };
const GRID = <CartesianGrid stroke="#e9e8e2" vertical={false} />;

function fmtFor(unit: string) {
  return unit === "percent" ? "percent" : unit === "pp" ? "pp" : unit === "currency_minor" ? "currency_minor" : "count";
}

function ChartTooltip({ active, payload, label, unit }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-semibold text-slate-800">{typeof label === "string" ? label : String(label)}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2 text-slate-600">
          <span className="inline-block h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span>{p.name}:</span>
          <span className="font-medium text-slate-900">{formatValue(p.value, fmtFor(p.payload?.__unit ?? unit))}</span>
        </div>
      ))}
    </div>
  );
}

function seriesColor(spec: ChartSpec, i: number): string {
  if (spec.type === "grouped_bar" && spec.series.length === 2 && /prev/i.test(spec.series[0].label)) return i === 0 ? PREVIOUS_COLOR : CURRENT_COLOR;
  if (spec.type === "band" && i >= 1) return i === 1 ? "#898781" : "#c3c2b7";
  return SERIES_COLORS[i % SERIES_COLORS.length];
}

export function ChartView({ spec, height = 260 }: { spec: ChartSpec; height?: number }) {
  const isDay = spec.x_key === "day";
  const xTick = (v: any) => (isDay ? shortDay(String(v)) : String(v).length > 14 ? String(v).slice(0, 13) + "…" : String(v));
  const many = spec.data.length > 6 && !isDay;

  if (spec.type === "composed") {
    // Metric and volume are different scales: two aligned panels, never a dual axis.
    const metric = spec.series[0];
    const vol = spec.series.find((s) => s.key === "attempts" && s !== metric);
    return (
      <div>
        <ResponsiveContainer width="100%" height={vol ? height * 0.68 : height}>
          <LineChart data={spec.data} syncId={spec.id} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            {GRID}
            <XAxis dataKey="day" {...AXIS} tickFormatter={xTick} hide={!!vol} minTickGap={24} />
            <YAxis {...AXIS} width={52} domain={["auto", "auto"]} tickFormatter={(v) => formatTick(v, spec.unit)} />
            <Tooltip content={<ChartTooltip unit={spec.unit} />} />
            {spec.reference_areas?.map((a) => (
              <ReferenceArea key={a.label} x1={a.x1} x2={a.x2} fill="#2a78d6" fillOpacity={0.06} label={{ value: a.label, position: "insideTop", fontSize: 10, fill: "#64748b" }} />
            ))}
            <Line type="monotone" dataKey={metric.key} name={metric.label} stroke={SERIES_COLORS[0]} strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
          </LineChart>
        </ResponsiveContainer>
        {vol && (
          <>
            <div className="mt-1 text-[11px] font-medium text-slate-500">Daily attempts</div>
            <ResponsiveContainer width="100%" height={height * 0.32}>
              <BarChart data={spec.data.map((d) => ({ ...d, __unit: "count" }))} syncId={spec.id} margin={{ top: 2, right: 12, left: 0, bottom: 0 }}>
                <XAxis dataKey="day" {...AXIS} tickFormatter={xTick} minTickGap={24} />
                <YAxis {...AXIS} width={52} tickFormatter={(v) => formatTick(v, "count")} />
                <Tooltip content={<ChartTooltip unit="count" />} cursor={{ fill: "#f1f5f9" }} />
                <Bar dataKey="attempts" name="Attempts" fill="#9ec5f4" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </>
        )}
      </div>
    );
  }

  if (spec.type === "line" || spec.type === "band") {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={spec.data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          {GRID}
          <XAxis dataKey={spec.x_key} {...AXIS} tickFormatter={xTick} minTickGap={24} />
          <YAxis {...AXIS} width={52} domain={["auto", "auto"]} tickFormatter={(v) => formatTick(v, spec.unit)} />
          <Tooltip content={<ChartTooltip unit={spec.unit} />} />
          {spec.series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} iconType="plainline" />}
          {spec.series.map((s, i) => (
            <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={seriesColor(spec, i)} strokeWidth={spec.type === "band" && i > 0 ? 1.5 : 2}
              strokeDasharray={spec.type === "band" && i >= 2 ? "4 4" : undefined} connectNulls
              dot={spec.type === "band" && i === 0 ? (p: any) => (p.payload.flagged ? <circle key={p.key} cx={p.cx} cy={p.cy} r={5} fill="#d03b3b" stroke="#fff" strokeWidth={2} /> : <g key={p.key} />) : false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  // bar, grouped_bar, stacked_bar
  const stacked = spec.type === "stacked_bar";
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={spec.data} margin={{ top: 8, right: 12, left: 0, bottom: many ? 40 : 0 }} barGap={2}>
        {GRID}
        <XAxis dataKey={spec.x_key} {...AXIS} tickFormatter={xTick} interval={0} angle={many ? -30 : 0} textAnchor={many ? "end" : "middle"} height={many ? 60 : 30} />
        <YAxis {...AXIS} width={52} tickFormatter={(v) => formatTick(v, spec.unit)} domain={spec.unit === "percent" && spec.type !== "bar" ? ["auto", "auto"] : [0, "auto"]} />
        <Tooltip content={<ChartTooltip unit={spec.unit} />} cursor={{ fill: "#f1f5f9" }} />
        {spec.series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} verticalAlign="top" height={24} />}
        {stacked && <ReferenceLine y={0} stroke="#94a3b8" />}
        {spec.reference_lines?.map((r) => (
          <ReferenceLine key={r.label} y={r.y} stroke="#52514e" strokeDasharray="4 4" label={{ value: r.label, position: "insideTopRight", fontSize: 10, fill: "#52514e" }} />
        ))}
        {spec.series.map((s, i) => (
          <Bar key={s.key} dataKey={s.key} name={s.label} fill={seriesColor(spec, i)} stackId={stacked ? "s" : undefined} radius={stacked ? 0 : [4, 4, 0, 0]} maxBarSize={48}>
            {spec.highlight_key && spec.data.map((d, j) => <Cell key={j} fill={d[spec.highlight_key!] ? "#d03b3b" : seriesColor(spec, i)} />)}
          </Bar>
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ChartCard({ spec, height }: { spec: ChartSpec; height?: number }) {
  return (
    <div className="card p-4">
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800">{spec.title}</h3>
        {spec.highlight_key && <span className="chip bg-red-50 text-red-700">red = flagged outlier</span>}
      </div>
      {spec.data.length ? <ChartView spec={spec} height={height} /> : <div className="py-10 text-center text-sm text-slate-400">No data for this chart.</div>}
    </div>
  );
}
