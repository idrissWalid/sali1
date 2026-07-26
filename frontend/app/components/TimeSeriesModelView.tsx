"use client";

import React from "react";
import { toggleTheme, useTheme } from "@/hooks/use-theme";
import {
  ArrowLeft, CheckCircle2, XCircle, AlertTriangle, MinusCircle, Sun, Moon,
  TrendingUp, Target, Gauge, Activity, BarChart3, Download,
} from "lucide-react";
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";

interface Coefficient { nom: string; valeur: number; p_value: number }
// valeur nullable : une observation manquante crée une rupture dans la courbe.
interface HistoPoint { date: string; valeur: number | null }
interface ForecastPoint { date: string; valeur_prevue: number; ic_bas?: number; ic_haut?: number }

export interface TimeSeriesReport {
  serie?: { n_observations?: number; frequence?: string; saisonnalite_detectee?: number | null };
  transformation?: { log_applique?: boolean; justification?: string };
  stationnarite?: { d?: number; D?: number; adf_p_value_finale?: number; kpss_p_value_finale?: number };
  modele_retenu?: {
    type?: string; ordre?: number[]; ordre_saisonnier?: number[] | null;
    aic?: number; bic?: number; coefficients?: Coefficient[];
  };
  gate_1_diagnostics_residus?: {
    ljung_box_p_lag_s?: number; ljung_box_p_lag_2s?: number; jarque_bera_p?: number; arch_p?: number; statut?: string;
  };
  gate_2_validation_out_of_sample?: {
    horizon_test?: number; mape_pct?: number; rmse?: number; couverture_ic95_pct?: number; statut?: string;
  };
  statut_final?: string;
  avertissements?: string[];
  historique?: HistoPoint[];
  prevision?: ForecastPoint[];
  forecast_chart?: string;
  resume_timecopilot?: string;
  // Contrat de sortie de TimeCopilot, conservé sous ses noms d'origine.
  tsfeatures_results?: string[];
  tsfeatures_analysis?: string;
  model_details?: string;
  cross_validation_results?: string[];
  cross_validation_metric?: string;
  model_comparison?: string;
  is_better_than_seasonal_naive?: boolean | null;
  reason_for_selection?: string;
  forecast_analysis?: string;
  anomaly_analysis?: string;
  user_query_response?: string;
  _engine?: string;
}

interface ModelInfo {
  id: string;
  name: string;
  type: string;
  created_at: string;
  metrics: TimeSeriesReport;
}

const num = (v: unknown, d = 3) => (typeof v === "number" && isFinite(v) ? v.toFixed(d) : "—");

/** Nombre lisible à l'écran (séparateur de milliers français). */
const fr = (v?: number | null) =>
  typeof v === "number" && isFinite(v) ? v.toLocaleString("fr-FR", { maximumFractionDigits: 2 }) : "—";

/** CSV à séparateur point-virgule et décimales à la virgule : c'est le format
 *  qu'Excel ouvre directement en locale française. Le BOM préserve les accents. */
function previsionsToCsv(rows: ForecastPoint[]): string {
  const dec = (n?: number) => (typeof n === "number" && isFinite(n) ? n.toFixed(4).replace(".", ",") : "");
  const lignes = rows.map((p) => [p.date, dec(p.valeur_prevue), dec(p.ic_bas), dec(p.ic_haut)].join(";"));
  return ["Date;Prevision;IC bas 95%;IC haut 95%", ...lignes].join("\r\n");
}

function telechargerPrevisions(rows: ForecastPoint[], nomModele: string) {
  const blob = new Blob(["\uFEFF" + previsionsToCsv(rows)], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `previsions_${(nomModele || "modele").replace(/[^\w-]+/g, "_")}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

function StatutBadge({ statut }: { statut?: string }) {
  const map: Record<string, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
    MODELE_VALIDE: { label: "Modèle validé", cls: "bg-green-50 text-green-700 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800", Icon: CheckCircle2 },
    MODELE_REJETE: { label: "Modèle rejeté", cls: "bg-red-50 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800", Icon: XCircle },
    INCERTITUDE_ELEVEE: { label: "Incertitude élevée", cls: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800", Icon: AlertTriangle },
    INFO_TIMECOPILOT: { label: "TimeCopilot", cls: "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800", Icon: MinusCircle },
  };
  const m = map[statut ?? ""] ?? { label: statut ?? "Inconnu", cls: "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700", Icon: MinusCircle };
  const Icon = m.Icon;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium ${m.cls}`}>
      <Icon size={15} /> {m.label}
    </span>
  );
}

function GateBadge({ statut }: { statut?: string }) {
  if (statut === "PASS") return <span className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold bg-green-50 text-green-700 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800"><CheckCircle2 size={12} /> PASS</span>;
  if (statut === "FAIL") return <span className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold bg-red-50 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800"><XCircle size={12} /> FAIL</span>;
  return <span className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold bg-gray-100 text-gray-500 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-700">NON CALCULÉ</span>;
}

function StatTile({ icon: Icon, label, value, accent, delay }: { icon: React.ComponentType<{ className?: string }>; label: string; value: React.ReactNode; accent?: string; delay: number }) {
  return (
    <div className="dashboard-stat bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm flex items-start gap-4 ts-card" style={{ animationDelay: `${delay}ms` }}>
      <div className={`p-3 rounded-xl ${accent ?? "bg-gray-50 dark:bg-[#222] text-blue-500"}`}>
        <Icon className="w-6 h-6" />
      </div>
      <div className="min-w-0">
        <p className="text-sm text-gray-500 dark:text-gray-400 font-medium">{label}</p>
        <p className="mt-1 text-2xl font-bold truncate">{value}</p>
      </div>
    </div>
  );
}

function Card({ title, extra, children, delay }: { title: React.ReactNode; extra?: React.ReactNode; children: React.ReactNode; delay: number }) {
  return (
    <div className="dashboard-panel bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm ts-card" style={{ animationDelay: `${delay}ms` }}>
      <div className="mb-4 flex items-center justify-between gap-2 border-b border-gray-100 dark:border-gray-800 pb-3">
        <h3 className="text-sm font-bold uppercase tracking-wide text-gray-600 dark:text-gray-300">{title}</h3>
        {extra}
      </div>
      {children}
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm border-b border-gray-50 dark:border-gray-800/50 last:border-0">
      <span className="text-gray-500 dark:text-gray-400">{k}</span>
      <span className="font-mono text-gray-900 dark:text-gray-100">{v}</span>
    </div>
  );
}

function Prose({ texte }: { texte: string }) {
  return <p className="text-sm leading-relaxed text-gray-600 dark:text-gray-300">{texte}</p>;
}

/** Restitution du raisonnement de TimeCopilot : caractéristiques de la série,
 *  comparaison des modèles, et réponse à la question posée. */
function TimeCopilotPanel({ r, delay }: { r: TimeSeriesReport; delay: number }) {
  const cv = r.cross_validation_results ?? [];
  const feats = r.tsfeatures_results ?? [];
  const baseline = r.is_better_than_seasonal_naive;

  return (
    <>
      {r.user_query_response && (
        <Card title="Réponse à votre question" delay={delay}>
          <Prose texte={r.user_query_response} />
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {(feats.length > 0 || r.tsfeatures_analysis) && (
          <Card title="Caractéristiques de la série" delay={delay + 30}>
            {feats.map((f) => {
              const [k, v] = f.includes(":") ? [f.slice(0, f.indexOf(":")), f.slice(f.indexOf(":") + 1)] : [f, ""];
              return <Row key={f} k={k.trim()} v={v.trim() || "—"} />;
            })}
            {r.tsfeatures_analysis && (
              <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
                <Prose texte={r.tsfeatures_analysis} />
              </div>
            )}
          </Card>
        )}

        {(cv.length > 0 || r.model_comparison) && (
          <Card
            title="Modèles en concurrence"
            delay={delay + 60}
            extra={
              baseline == null ? null : (
                <span
                  className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-semibold ${
                    baseline
                      ? "bg-green-50 text-green-700 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800"
                      : "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800"
                  }`}
                >
                  {baseline ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
                  {baseline ? "bat SeasonalNaive" : "ne bat pas SeasonalNaive"}
                </span>
              )
            }
          >
            {cv.map((c) => {
              const [k, v] = c.includes(":") ? [c.slice(0, c.indexOf(":")), c.slice(c.indexOf(":") + 1)] : [c, ""];
              const retenu = k.trim() === r.modele_retenu?.type;
              return (
                <div key={c} className="flex items-center justify-between gap-3 py-1.5 text-sm border-b border-gray-50 dark:border-gray-800/50 last:border-0">
                  <span className={retenu ? "font-semibold text-gray-900 dark:text-gray-100" : "text-gray-500 dark:text-gray-400"}>
                    {k.trim()} {retenu && <span className="ml-1 text-xs font-normal text-blue-500">retenu</span>}
                  </span>
                  <span className="font-mono text-gray-900 dark:text-gray-100">{v.trim() || "—"}</span>
                </div>
              );
            })}
            {r.cross_validation_metric && (
              <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
                Scores en {r.cross_validation_metric.toUpperCase()} sur validation croisée — plus bas est meilleur.
              </p>
            )}
            {r.model_comparison && (
              <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
                <Prose texte={r.model_comparison} />
              </div>
            )}
          </Card>
        )}
      </div>

      {(r.reason_for_selection || r.model_details || r.forecast_analysis) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {(r.reason_for_selection || r.model_details) && (
            <Card title="Pourquoi ce modèle" delay={delay + 90}>
              {r.reason_for_selection && <Prose texte={r.reason_for_selection} />}
              {r.model_details && (
                <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
                  <Prose texte={r.model_details} />
                </div>
              )}
            </Card>
          )}
          {(r.forecast_analysis || r.anomaly_analysis) && (
            <Card title="Lecture de la prévision" delay={delay + 120}>
              {r.forecast_analysis && <Prose texte={r.forecast_analysis} />}
              {r.anomaly_analysis && (
                <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
                  <Prose texte={r.anomaly_analysis} />
                </div>
              )}
            </Card>
          )}
        </div>
      )}
    </>
  );
}

function ForecastTable({ rows, nomModele, delay }: { rows: ForecastPoint[]; nomModele: string; delay: number }) {
  const avecIC = rows.some((p) => p.ic_bas != null || p.ic_haut != null);
  return (
    <Card
      title="Tableau des prévisions (IC 95%)"
      delay={delay}
      extra={
        <button
          onClick={() => telechargerPrevisions(rows, nomModele)}
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#222] px-3 py-1.5 text-xs font-medium shadow-sm transition-colors hover:bg-gray-50 dark:hover:bg-[#2a2a2a]"
        >
          <Download size={14} /> Télécharger (CSV)
        </button>
      }
    >
      <div className="ts-scroll max-h-[420px] overflow-auto rounded-xl border border-gray-100 dark:border-gray-800">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 z-10 bg-gray-50 dark:bg-[#202020]">
            <tr className="text-left text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
              <th className="px-4 py-2.5 font-semibold">Date</th>
              <th className="px-4 py-2.5 text-right font-semibold">Prévision</th>
              <th className="px-4 py-2.5 text-right font-semibold">IC bas</th>
              <th className="px-4 py-2.5 text-right font-semibold">IC haut</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.date} className="border-t border-gray-100 dark:border-gray-800/70 hover:bg-gray-50 dark:hover:bg-[#1f1f1f]">
                <td className="px-4 py-2 whitespace-nowrap text-gray-600 dark:text-gray-300">{p.date}</td>
                <td className="px-4 py-2 text-right font-mono font-semibold text-gray-900 dark:text-gray-100">{fr(p.valeur_prevue)}</td>
                <td className="px-4 py-2 text-right font-mono text-gray-500 dark:text-gray-400">{fr(p.ic_bas)}</td>
                <td className="px-4 py-2 text-right font-mono text-gray-500 dark:text-gray-400">{fr(p.ic_haut)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-xs text-gray-400 dark:text-gray-500">
        {rows.length} période{rows.length > 1 ? "s" : ""} prévue{rows.length > 1 ? "s" : ""}
        {avecIC ? " — intervalle de confiance à 95%." : " — aucun intervalle de confiance fourni par ce modèle."}
      </p>
    </Card>
  );
}

export default function TimeSeriesModelView({ model, onBack }: { model: ModelInfo; onBack: () => void }) {
  // Le thème vit dans l'attribut data-theme de <html> : on s'y abonne au lieu de
  // le recopier dans un state depuis un effet (rendu en cascade au montage).
  const theme = useTheme();

  const r = model.metrics || {};
  const modele = r.modele_retenu || {};
  const ordre = modele.ordre ? `(${modele.ordre.join(", ")})` : "—";
  const ordreSais = modele.ordre_saisonnier ? `(${modele.ordre_saisonnier.join(", ")})` : "—";
  const modelLabel = modele.type
    ? (modele.ordre
        ? `${modele.type} ${ordre}${modele.ordre_saisonnier ? `×(${modele.ordre_saisonnier.join(",")})` : ""}`
        : modele.type)
    : (r._engine === "autoforecast" || r._engine === "timecopilot" ? "Prévision automatique" : "—");

  // L'intervalle est fourni à recharts comme un tuple [bas, haut] (« ranged
  // Area »). Deux <Area> partageant un stackId seraient EMPILÉES : le haut de la
  // bande serait dessiné à ic_bas + ic_haut, très au-dessus de la borne réelle.
  const chartData: Record<string, number | string | null | undefined | [number, number]>[] = [
    ...(r.historique ?? []).map((h) => ({ date: h.date, historique: h.valeur })),
    ...(r.prevision ?? []).map((p) => ({
      date: p.date,
      prevue: p.valeur_prevue,
      ...(p.ic_bas != null && p.ic_haut != null
        ? { ic: [p.ic_bas, p.ic_haut] as [number, number] }
        : {}),
    })),
  ];
  const hasChartData = chartData.length > 0;
  const tooltipStyle = theme === "dark"
    ? { borderRadius: 12, border: "1px solid #333", background: "rgba(20,20,20,0.95)", color: "#fff" }
    : { borderRadius: 12, border: "1px solid #e5e7eb", background: "#fff", color: "#111" };

  return (
    <div className="dashboard-shell min-h-screen w-full bg-gray-50 dark:bg-[#111] text-gray-900 dark:text-gray-100 font-sans">
      <style>{`
        @keyframes ts-fade-up { from { opacity: 0; transform: translateY(10px) } to { opacity: 1; transform: translateY(0) } }
        .ts-card { animation: ts-fade-up .45s ease-out both; }
        .ts-scroll::-webkit-scrollbar { height: 6px; width: 6px; }
        .ts-scroll::-webkit-scrollbar-thumb { background-color: rgba(150,150,150,.3); border-radius: 10px; }
        .dashboard-shell { padding: 32px clamp(20px, 4vw, 72px) 48px; }
        .dashboard-container { width: min(100%, 1680px); margin: 0 auto; display: grid; gap: 24px; }
        .dashboard-header { gap: 24px; }
        .dashboard-stats { gap: 16px; }
        .dashboard-panel { padding: 24px; }
        .dashboard-stat { min-height: 104px; padding: 20px; }
      `}</style>

      <div className="dashboard-container">

        {/* Header */}
        <div className="dashboard-header flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{model.name}</h1>
            <p className="text-gray-500 dark:text-gray-400 mt-1 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-blue-500" /> Modèle de série temporelle
            </p>
          </div>
          <div className="flex items-center gap-2">
            <StatutBadge statut={r.statut_final} />
            <button
              onClick={toggleTheme}
              className="p-2 bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-[#333] transition flex items-center justify-center text-sm font-medium"
            >
              {theme === "dark" ? <Sun className="w-4 h-4 text-gray-400" /> : <Moon className="w-4 h-4 text-gray-500" />}
            </button>
            <button
              onClick={onBack}
              className="px-4 py-2 bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-[#333] transition flex items-center gap-2 text-sm font-medium"
            >
              <ArrowLeft className="w-4 h-4" /> Retour
            </button>
          </div>
        </div>

        {/* Global Stats Overview */}
        <div className="dashboard-stats grid grid-cols-2 md:grid-cols-4">
          <StatTile icon={BarChart3} label="Modèle retenu" value={modelLabel} delay={0} />
          <StatTile
            icon={Target}
            label="MAPE (out-of-sample)"
            value={r.gate_2_validation_out_of_sample?.mape_pct != null ? `${num(r.gate_2_validation_out_of_sample.mape_pct, 2)}%` : "—"}
            accent="text-emerald-500 bg-emerald-50 dark:bg-emerald-500/10"
            delay={60}
          />
          <StatTile
            icon={Gauge}
            label="Couverture IC 95%"
            value={r.gate_2_validation_out_of_sample?.couverture_ic95_pct != null ? `${num(r.gate_2_validation_out_of_sample.couverture_ic95_pct, 1)}%` : "—"}
            accent="text-violet-500 bg-violet-50 dark:bg-violet-500/10"
            delay={120}
          />
          <StatTile
            icon={Activity}
            label="AIC"
            value={num(modele.aic, 1)}
            accent="text-amber-500 bg-amber-50 dark:bg-amber-500/10"
            delay={180}
          />
        </div>

        {/* Forecast chart */}
        <div className="ts-card rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1a1a1a] p-6 shadow-sm" style={{ animationDelay: "220ms" }}>
          <h3 className="mb-5 text-sm font-bold uppercase tracking-wide text-gray-600 dark:text-gray-300">Historique &amp; prévision (IC 95%)</h3>
          {hasChartData ? (
            <div style={{ width: "100%", height: 360 }}>
              <ResponsiveContainer>
                <ComposedChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                  <XAxis dataKey="date" tick={{ fill: "#888", fontSize: 11 }} minTickGap={24} />
                  <YAxis tick={{ fill: "#888", fontSize: 11 }} width={56} />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    formatter={(value, name) =>
                      Array.isArray(value)
                        ? [`${fr(value[0] as number)} – ${fr(value[1] as number)}`, name ?? ""]
                        : [fr(value as number), name ?? ""]
                    }
                  />
                  <Legend />
                  <Area dataKey="ic" stroke="none" fill="#6366f1" fillOpacity={0.15} name="Intervalle 95%" />
                  <Line type="monotone" dataKey="historique" stroke="#3b82f6" strokeWidth={2} dot={false} name="Historique" connectNulls />
                  <Line type="monotone" dataKey="prevue" stroke="#f59e0b" strokeWidth={2.5} dot={false} name="Prévision" connectNulls />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : r.forecast_chart ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`data:image/png;base64,${r.forecast_chart}`} alt="Prévision" className="w-full rounded-xl" />
          ) : (
            <p className="py-10 text-center text-sm text-gray-400">Aucun graphique de prévision disponible.</p>
          )}
        </div>

        {/* Tableau des prévisions, téléchargeable */}
        {(r.prevision ?? []).length > 0 && (
          <ForecastTable rows={r.prevision ?? []} nomModele={model.name} delay={250} />
        )}

        {r._engine === "timecopilot" && <TimeCopilotPanel r={r} delay={255} />}

        {r.resume_timecopilot && (
          <Card title="Résumé TimeCopilot" delay={260}>
            <pre className="ts-scroll max-h-56 overflow-auto whitespace-pre-wrap font-sans text-sm leading-relaxed text-gray-600 dark:text-gray-300">{r.resume_timecopilot}</pre>
          </Card>
        )}

        {/* Gates */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card title="GATE 1 — Diagnostic des résidus" extra={<GateBadge statut={r.gate_1_diagnostics_residus?.statut} />} delay={280}>
            <Row k="Ljung-Box (lag s)" v={num(r.gate_1_diagnostics_residus?.ljung_box_p_lag_s)} />
            <Row k="Ljung-Box (lag 2s)" v={num(r.gate_1_diagnostics_residus?.ljung_box_p_lag_2s)} />
            <Row k="Jarque-Bera (normalité)" v={num(r.gate_1_diagnostics_residus?.jarque_bera_p)} />
            <Row k="Test ARCH (hétéroscédasticité)" v={num(r.gate_1_diagnostics_residus?.arch_p)} />
          </Card>
          <Card title="GATE 2 — Validation out-of-sample" extra={<GateBadge statut={r.gate_2_validation_out_of_sample?.statut} />} delay={320}>
            <Row k="Horizon de test" v={r.gate_2_validation_out_of_sample?.horizon_test ?? "—"} />
            <Row k="MAPE (%)" v={num(r.gate_2_validation_out_of_sample?.mape_pct, 2)} />
            <Row k="RMSE" v={num(r.gate_2_validation_out_of_sample?.rmse, 2)} />
            <Row k="Couverture IC 95% (%)" v={num(r.gate_2_validation_out_of_sample?.couverture_ic95_pct, 1)} />
          </Card>
        </div>

        {/* Modèle + série */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card title="Modèle retenu" delay={360}>
            <Row k="Type" v={modele.type ?? "—"} />
            <Row k="Ordre (p, d, q)" v={ordre} />
            <Row k="Ordre saisonnier (P, D, Q, s)" v={ordreSais} />
            <Row k="AIC" v={num(modele.aic, 2)} />
            <Row k="BIC" v={num(modele.bic, 2)} />
            {modele.coefficients && modele.coefficients.length > 0 && (
              <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
                <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-gray-400">Coefficients</div>
                {modele.coefficients.map((c) => (
                  <Row key={c.nom} k={c.nom} v={`${num(c.valeur)} (p=${num(c.p_value)})`} />
                ))}
              </div>
            )}
          </Card>
          <Card title="Série & stationnarité" delay={400}>
            <Row k="Observations" v={r.serie?.n_observations ?? "—"} />
            <Row k="Fréquence" v={r.serie?.frequence ?? "—"} />
            <Row k="Saisonnalité détectée" v={r.serie?.saisonnalite_detectee ?? "—"} />
            <Row k="Différenciation d / D" v={`${r.stationnarite?.d ?? "—"} / ${r.stationnarite?.D ?? "—"}`} />
            <Row k="ADF p-value (finale)" v={num(r.stationnarite?.adf_p_value_finale)} />
            <Row k="KPSS p-value (finale)" v={num(r.stationnarite?.kpss_p_value_finale)} />
            <Row k="Log appliqué" v={r.transformation?.log_applique ? "oui" : "non"} />
          </Card>
        </div>

        {/* Avertissements */}
        {r.avertissements && r.avertissements.length > 0 && (
          <div className="ts-card rounded-2xl border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-900/10 p-6" style={{ animationDelay: "440ms" }}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-amber-700 dark:text-amber-400"><AlertTriangle size={15} /> Avertissements</h3>
            <ul className="list-disc list-inside space-y-1.5 text-sm text-amber-800 dark:text-amber-200/80">
              {r.avertissements.map((a, i) => <li key={i}>{a}</li>)}
            </ul>
          </div>
        )}

        <div className="text-center text-xs text-gray-400 dark:text-gray-600 pt-2">
          Créé le {new Date(model.created_at).toLocaleString("fr-FR")}
        </div>
      </div>
    </div>
  );
}
