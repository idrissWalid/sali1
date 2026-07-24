"use client";

import {
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  Columns3,
  Copy,
  Info,
  Loader2,
  Moon,
  Rows3,
  Sun,
  Table2,
} from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { getDashboardData } from "../../lib/api";
import type { DashboardData } from "../../lib/types";

const COLORS = ["#34d399", "#8b7cf6", "#60a5fa", "#f59e0b", "#f87171", "#22d3ee", "#a3e635", "#f472b6", "#fb923c"];

// Sur un axe temporel proportionnel, la granularité des libellés doit suivre
// l'amplitude couverte, sinon les dates se chevauchent ou perdent leur sens.
const formatTimeTick = (ts: number, spanDays: number) => {
  const date = new Date(ts);
  if (spanDays <= 2) return date.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  if (spanDays <= 90) return date.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
  if (spanDays <= 1095) return date.toLocaleDateString("fr-FR", { month: "short", year: "2-digit" });
  return date.getFullYear().toString();
};

function StatCard({ title, value, icon: Icon }: { title: string; value: string | number; icon: React.ComponentType<{ size?: number; strokeWidth?: number }> }) {
  return (
    <div className="flex items-start gap-3.5 rounded-lg border p-5" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }}>
      <div className="grid size-11 shrink-0 place-items-center rounded-md" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
        <Icon size={20} strokeWidth={1.8} />
      </div>
      <div>
        <p className="text-[12px] font-medium" style={{ color: "var(--text-muted)" }}>{title}</p>
        <p className="mt-1 text-[22px] font-bold" style={{ color: "var(--text-main)" }}>{value}</p>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selectedVar, setSelectedVar] = useState("");
  const [theme, setTheme] = useState<"dark" | "light">("light");
  const [selectedDataset, setSelectedDataset] = useState("");
  // Granularité temporelle choisie manuellement ; vide = celle proposée par défaut.
  const [granularity, setGranularity] = useState("");

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (!sessionId) return;
    getDashboardData(sessionId, selectedDataset || undefined)
      .then((json) => {
        setData(json);
        // Les variables diffèrent d'un dataset à l'autre : on ne garde la
        // sélection courante que si elle existe encore.
        const vars = Object.keys(json.distributions || {});
        setSelectedVar((current) => (current && vars.includes(current) ? current : vars[0] ?? ""));
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Erreur de récupération"))
      .finally(() => setLoading(false));
  }, [sessionId, selectedDataset]);

  if (loading) {
    return (
      <div className="flex h-screen w-full items-center justify-center" style={{ background: "var(--bg-app)" }}>
        <Loader2 className="animate-spin" size={28} style={{ color: "var(--accent)" }} />
        <span className="ml-3 text-[16px] font-medium" style={{ color: "var(--text-main)" }}>Chargement du dashboard...</span>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex h-screen w-full items-center justify-center" style={{ background: "var(--bg-app)" }}>
        <div className="rounded-lg border p-6" style={{ borderColor: "var(--danger)", color: "var(--danger)" }}>
          <h2 className="mb-2 text-[18px] font-bold">Erreur</h2>
          <p>{error || "Données introuvables"}</p>
        </div>
      </div>
    );
  }

  const { overview, preview, variables, distributions, filename } = data;
  const activeDist = selectedVar ? distributions[selectedVar] : null;

  // Le backend choisit le graphique adapté à la nature de la colonne. Le repli
  // couvre les sessions analysées avant l'ajout du champ `chart`.
  const chartKind =
    activeDist?.chart ??
    (activeDist?.type === "categorical"
      ? "donut"
      : activeDist?.type === "numeric"
        ? "histogram"
        : activeDist?.type === "timeseries" || activeDist?.type === "datetime"
          ? "line"
          : null);

  // Séries temporelles : toutes les granularités sont livrées dans la même
  // réponse, la bascule d'échelle est donc immédiate.
  const granularityOptions = activeDist?.granularities ?? [];
  const activeGranularity =
    granularity && activeDist?.series?.[granularity]
      ? granularity
      : activeDist?.default_granularity ?? "";
  const chartData =
    (activeGranularity && activeDist?.series?.[activeGranularity]) || activeDist?.data || [];

  const timestamps = chartData
    .map((point) => point.ts)
    .filter((ts): ts is number => typeof ts === "number");
  const hasTimestamps = timestamps.length > 1;
  const spanDays = hasTimestamps
    ? (Math.max(...timestamps) - Math.min(...timestamps)) / 86_400_000
    : 0;

  const datasets = data.datasets ?? [];

  return (
    <div className="min-h-screen w-full font-sans" style={{ background: "var(--bg-app)", color: "var(--text-main)" }}>
      <div className="mx-auto grid w-full max-w-[1680px] gap-6 px-5 py-8 sm:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="font-serif text-[28px] font-medium tracking-tight">Dashboard Analytique</h1>
            <p className="mt-1 flex items-center gap-2 text-[13px]" style={{ color: "var(--text-muted)" }}>
              <Table2 size={15} /> Fichier source : <span className="font-semibold" style={{ color: "var(--text-main)" }}>{filename}</span>
            </p>
          </div>
          <div className="flex gap-2">
            {/* Sélecteur de jeu de données : une session peut en porter
                plusieurs (fichier principal, tableau extrait, ajouts). */}
            {datasets.length > 1 && (
              <select
                value={data.dataset_id ?? ""}
                onChange={(event) => setSelectedDataset(event.target.value)}
                className="max-w-[280px] rounded-md border px-3 py-2 text-[13px] font-medium"
                style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)", color: "var(--text-main)" }}
                aria-label="Jeu de données"
              >
                {datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name}
                    {dataset.rows ? ` (${dataset.rows} lignes)` : ""}
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              className="grid size-9 place-items-center rounded-md border transition-colors hover:bg-[var(--bubble-ai)]"
              style={{ borderColor: "var(--border-color)" }}
            >
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button
              onClick={() => window.close()}
              className="flex items-center gap-2 rounded-md border px-4 py-2 text-[13px] font-medium transition-colors hover:bg-[var(--bubble-ai)]"
              style={{ borderColor: "var(--border-color)" }}
            >
              <ArrowLeft size={15} /> Fermer l&rsquo;onglet
            </button>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatCard title="Lignes" value={overview.n_lignes?.toLocaleString() ?? 0} icon={Rows3} />
          <StatCard title="Colonnes" value={overview.n_colonnes?.toLocaleString() ?? 0} icon={Columns3} />
          <StatCard title="Valeurs manquantes" value={`${overview.pct_valeurs_manquantes_total ?? 0}%`} icon={AlertTriangle} />
          <StatCard title="Doublons" value={overview.n_doublons?.toLocaleString() ?? 0} icon={Copy} />
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <div className="flex min-h-[500px] flex-col rounded-lg border p-6 lg:col-span-1" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }}>
            <div className="mb-3 flex items-center gap-2">
              <BarChart3 size={18} style={{ color: "var(--accent)" }} />
              <h2 className="text-[18px] font-bold">Variables</h2>
            </div>
            <p className="mb-4 text-[13px]" style={{ color: "var(--text-muted)" }}>Sélectionnez une variable pour visualiser sa distribution.</p>

            <div className="flex-1 space-y-2 overflow-y-auto pr-1">
              {Object.keys(variables).map((varName) => {
                const info = variables[varName];
                const isSelected = selectedVar === varName;
                return (
                  <button
                    key={varName}
                    onClick={() => setSelectedVar(varName)}
                    className="w-full rounded-md border px-4 py-3 text-left transition-all"
                    style={{
                      borderColor: isSelected ? "var(--accent)" : "transparent",
                      background: isSelected ? "var(--accent-soft)" : "var(--bubble-ai)",
                    }}
                  >
                    <div className="flex items-center justify-between">
                      <span className="mr-2 truncate font-medium" style={{ color: isSelected ? "var(--accent)" : "var(--text-main)" }}>{varName}</span>
                      <span className="shrink-0 rounded-md px-2 py-1 text-[11px]" style={{ background: "var(--border-color)", color: "var(--text-muted)" }}>
                        {info?.type ?? "inconnu"}
                      </span>
                    </div>
                    {(info?.pct_manquantes ?? 0) > 0 && (
                      <div className="mt-1 text-[11px]" style={{ color: "#f59e0b" }}>{info?.pct_manquantes}% manquantes</div>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex min-h-[500px] flex-col rounded-lg border p-6 lg:col-span-2" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }}>
            <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 text-[18px] font-bold">
                {activeDist?.type === "timeseries" ? "Évolution temporelle de" : "Distribution de"}{" "}
                <span style={{ color: "var(--accent)" }}>{selectedVar}</span>
              </h2>

              {/* Échelle temporelle : les granularités sont déjà chargées, la
                  bascule est instantanée. */}
              {granularityOptions.length > 1 && (
                <div className="flex items-center gap-1 rounded-md border p-1" style={{ borderColor: "var(--border-color)" }}>
                  {granularityOptions.map((option) => (
                    <button
                      key={option.key}
                      onClick={() => setGranularity(option.key)}
                      className="rounded px-3 py-1 text-[13px] font-medium transition-colors"
                      style={
                        activeGranularity === option.key
                          ? { background: "var(--accent)", color: "#fff" }
                          : { color: "var(--text-muted)" }
                      }
                      title={`${option.points} points`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="min-h-[420px] flex-1">
              {!activeDist || chartData.length === 0 ? (
                <div className="flex h-full items-center justify-center" style={{ color: "var(--text-dim)" }}>
                  <div className="text-center">
                    <Info size={28} className="mx-auto mb-2 opacity-50" />
                    <p>Aucune donnée à visualiser pour cette variable.</p>
                  </div>
                </div>
              ) : chartKind === "donut" ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={chartData} cx="38%" cy="50%" innerRadius={72} outerRadius={126} paddingAngle={2} dataKey="value" label={false}>
                      {chartData.map((_, index) => <Cell key={index} fill={COLORS[index % COLORS.length]} />)}
                    </Pie>
                    <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #333", background: "rgba(20,20,20,0.92)", color: "#fff" }} itemStyle={{ color: "#fff" }} />
                    <Legend layout="vertical" verticalAlign="middle" align="right" wrapperStyle={{ right: 16, lineHeight: "24px" }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : chartKind === "hbar" ? (
                /* Barres horizontales : au-delà de ~5 catégories, les libellés
                   restent lisibles là où un camembert devient inexploitable. */
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} layout="vertical" margin={{ top: 10, right: 30, left: 10, bottom: 10 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.15} horizontal={false} />
                    <XAxis type="number" tick={{ fill: "#888", fontSize: 12 }} allowDecimals={false} />
                    <YAxis type="category" dataKey="name" tick={{ fill: "#888", fontSize: 12 }} width={150} interval={0} />
                    <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #333", background: "rgba(20,20,20,0.92)", color: "#fff" }} cursor={{ fill: "rgba(255,255,255,0.08)" }} />
                    <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                      {chartData.map((_, index) => <Cell key={index} fill={COLORS[index % COLORS.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : chartKind === "histogram" || chartKind === "bar" ? (
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 20, right: 30, left: 0, bottom: 50 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                    <XAxis dataKey="name" angle={-45} textAnchor="end" height={80} tick={{ fill: "#888", fontSize: 12 }} minTickGap={4} />
                    <YAxis tick={{ fill: "#888" }} allowDecimals={false} />
                    <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #333", background: "rgba(20,20,20,0.92)", color: "#fff" }} cursor={{ fill: "rgba(255,255,255,0.08)" }} />
                    <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                      {chartData.map((_, index) => <Cell key={index} fill={COLORS[index % COLORS.length]} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : chartKind === "line" ? (
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData} margin={{ top: 20, right: 30, left: 0, bottom: 50 }}>
                    <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                    {/* Axe temporel proportionnel dès que le backend fournit des
                        horodatages, au lieu d'un axe catégoriel régulier. */}
                    {hasTimestamps ? (
                      <XAxis
                        dataKey="ts"
                        type="number"
                        scale="time"
                        domain={["dataMin", "dataMax"]}
                        tick={{ fill: "#888", fontSize: 12 }}
                        tickFormatter={(ts: number) => formatTimeTick(ts, spanDays)}
                        minTickGap={30}
                        height={50}
                      />
                    ) : (
                      <XAxis dataKey="name" angle={-45} textAnchor="end" height={80} tick={{ fill: "#888", fontSize: 12 }} minTickGap={20} />
                    )}
                    <YAxis tick={{ fill: "#888" }} />
                    <Tooltip
                      contentStyle={{ borderRadius: 12, border: "1px solid #333", background: "rgba(20,20,20,0.92)", color: "#fff" }}
                      labelFormatter={(label: React.ReactNode) =>
                        hasTimestamps && (typeof label === "number" || typeof label === "string")
                          ? new Date(Number(label)).toLocaleDateString("fr-FR")
                          : String(label ?? "")
                      }
                    />
                    <Line type="monotone" dataKey="value" stroke="#34d399" strokeWidth={3} dot={false} activeDot={{ r: 4, fill: "#34d399" }} />
                  </LineChart>
                </ResponsiveContainer>
              ) : null}
            </div>
          </div>
        </div>

        <div className="overflow-hidden rounded-lg border p-6 pb-2" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }}>
          <h2 className="mb-4 text-[18px] font-bold">Aperçu des données (5 premières lignes)</h2>
          <div className="overflow-x-auto pb-4">
            <table className="w-full text-left text-[13px]">
              <thead className="text-[11px] uppercase" style={{ color: "var(--text-muted)", background: "var(--bubble-ai)" }}>
                <tr>
                  {Object.keys(preview[0] || {}).map((key) => (
                    <th key={key} className="whitespace-nowrap px-4 py-3 font-semibold">{key}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y" style={{ borderColor: "var(--border-muted)" }}>
                {preview.map((row, i) => (
                  <tr key={i} className="transition-colors hover:bg-[var(--bubble-ai)]">
                    {Object.values(row).map((val, j) => (
                      <td key={j} className="whitespace-nowrap px-4 py-3" style={{ color: "var(--text-muted)" }}>
                        {val === null ? <span className="italic opacity-60">null</span> : String(val)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
