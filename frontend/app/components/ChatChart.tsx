"use client";

import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line,
  LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

export interface ChatChartSpec {
  type: "line" | "bar" | "area" | "pie";
  title: string;
  x_key: string;
  series: { key: string; label?: string }[];
  data: Record<string, string | number | null>[];
}

const COLORS = ["#8ab4f8", "#c58af9", "#34a853", "#ea4335", "#fbbc04"];

export default function ChatChart({ chart }: { chart: ChatChartSpec }) {
  if (!chart.data?.length || !chart.series?.length) return null;
  const common = { data: chart.data, margin: { top: 8, right: 16, left: 0, bottom: 8 } };
  const axes = <>
    <CartesianGrid strokeDasharray="3 3" stroke="var(--border-muted)" />
    <XAxis dataKey={chart.x_key} tick={{ fill: "var(--text-muted)", fontSize: 11 }} />
    <YAxis tick={{ fill: "var(--text-muted)", fontSize: 11 }} />
    <Tooltip contentStyle={{ background: "var(--bg-panel)", border: "1px solid var(--border-color)", borderRadius: 8 }} />
    <Legend />
  </>;

  return (
    <section className="mt-3 rounded-xl border border-[var(--border-color)] bg-[var(--bg-panel)] p-4">
      <h3 className="mb-3 text-sm font-semibold text-[var(--text-main)]">{chart.title}</h3>
      <div className="h-80 w-full" aria-label={chart.title}>
        <ResponsiveContainer width="100%" height="100%">
          {chart.type === "pie" ? (
            <PieChart>
              <Tooltip contentStyle={{ background: "var(--bg-panel)", border: "1px solid var(--border-color)", borderRadius: 8 }} />
              <Legend />
              <Pie data={chart.data} dataKey={chart.series[0].key} nameKey={chart.x_key} outerRadius="78%" label>
                {chart.data.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
            </PieChart>
          ) : chart.type === "bar" ? (
            <BarChart {...common}>{axes}{chart.series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.label ?? s.key} fill={COLORS[i % COLORS.length]} />)}</BarChart>
          ) : chart.type === "area" ? (
            <AreaChart {...common}>{axes}{chart.series.map((s, i) => <Area key={s.key} type="monotone" dataKey={s.key} name={s.label ?? s.key} stroke={COLORS[i % COLORS.length]} fill={COLORS[i % COLORS.length]} fillOpacity={0.2} connectNulls={false} />)}</AreaChart>
          ) : (
            <LineChart {...common}>{axes}{chart.series.map((s, i) => <Line key={s.key} type="monotone" dataKey={s.key} name={s.label ?? s.key} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={chart.data.length <= 40} connectNulls={false} />)}</LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </section>
  );
}
