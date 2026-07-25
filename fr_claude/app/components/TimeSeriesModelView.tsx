"use client";

import React from "react";
import {
  ArrowLeft, CheckCircle2, XCircle, AlertTriangle, MinusCircle,
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
  const map: Record<string, { label: string; color: string; Icon: typeof CheckCircle2 }> = {
    MODELE_VALIDE: { label: "Modèle validé", color: "#34d399", Icon: CheckCircle2 },
    MODELE_REJETE: { label: "Modèle rejeté", color: "#f87171", Icon: XCircle },
    INCERTITUDE_ELEVEE: { label: "Incertitude élevée", color: "#f59e0b", Icon: AlertTriangle },
    INFO_TIMECOPILOT: { label: "TimeCopilot", color: "#60a5fa", Icon: MinusCircle },
  };
  const m = map[statut ?? ""] ?? { label: statut ?? "Inconnu", color: "var(--text-muted)", Icon: MinusCircle };
  const Icon = m.Icon;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-[13px] font-medium" style={{ color: m.color, borderColor: m.color, background: `color-mix(in srgb, ${m.color} 12%, transparent)` }}>
      <Icon size={15} /> {m.label}
    </span>
  );
}

function GateBadge({ statut }: { statut?: string }) {
  const color = statut === "PASS" ? "#34d399" : statut === "FAIL" ? "#f87171" : "var(--text-muted)";
  const label = statut === "PASS" ? "PASS" : statut === "FAIL" ? "FAIL" : "NON CALCULÉ";
  const Icon = statut === "PASS" ? CheckCircle2 : statut === "FAIL" ? XCircle : MinusCircle;
  return (
    <span className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold" style={{ color, borderColor: color }}>
      <Icon size={12} /> {label}
    </span>
  );
}

function StatTile({ icon: Icon, label, value, color, delay }: { icon: React.ComponentType<{ size?: number; strokeWidth?: number }>; label: string; value: React.ReactNode; color: string; delay: number }) {
  return (
    <div className="fc-fade-up flex items-start gap-3.5 rounded-lg border p-5" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)", animationDelay: `${delay}ms` }}>
      <div className="grid size-11 shrink-0 place-items-center rounded-md" style={{ background: `color-mix(in srgb, ${color} 14%, transparent)`, color }}>
        <Icon size={20} strokeWidth={1.8} />
      </div>
      <div className="min-w-0">
        <p className="text-[12px] font-medium" style={{ color: "var(--text-muted)" }}>{label}</p>
        <p className="mt-1 truncate text-[20px] font-bold" style={{ color: "var(--text-main)" }}>{value}</p>
      </div>
    </div>
  );
}

function Card({ title, children, delay }: { title: React.ReactNode; children: React.ReactNode; delay: number }) {
  return (
    <div className="fc-fade-up rounded-lg border p-5" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)", animationDelay: `${delay}ms` }}>
      <h3 className="mb-3 flex items-center justify-between gap-2 border-b pb-2 text-[12px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)", borderColor: "var(--border-muted)" }}>{title}</h3>
      {children}
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b py-1.5 text-[13px] last:border-0" style={{ borderColor: "color-mix(in srgb, var(--border-muted) 50%, transparent)" }}>
      <span style={{ color: "var(--text-muted)" }}>{k}</span>
      <span className="font-mono" style={{ color: "var(--text-main)" }}>{v}</span>
    </div>
  );
}

function Prose({ texte }: { texte: string }) {
  return <p className="text-[13px] leading-relaxed" style={{ color: "var(--text-muted)" }}>{texte}</p>;
}

/** Restitution du raisonnement de TimeCopilot : caractéristiques de la série,
 *  comparaison des modèles, et réponse à la question posée. */
function TimeCopilotPanel({ r, delay }: { r: TimeSeriesReport; delay: number }) {
  const cv = r.cross_validation_results ?? [];
  const feats = r.tsfeatures_results ?? [];
  const baseline = r.is_better_than_seasonal_naive;
  const couleurBaseline = baseline ? "#34d399" : "#fbbf24";

  return (
    <>
      {r.user_query_response && (
        <Card title="Réponse à votre question" delay={delay}>
          <Prose texte={r.user_query_response} />
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {(feats.length > 0 || r.tsfeatures_analysis) && (
          <Card title="Caractéristiques de la série" delay={delay + 30}>
            {feats.map((f) => {
              const [k, v] = f.includes(":") ? [f.slice(0, f.indexOf(":")), f.slice(f.indexOf(":") + 1)] : [f, ""];
              return <Row key={f} k={k.trim()} v={v.trim() || "—"} />;
            })}
            {r.tsfeatures_analysis && (
              <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--border-muted)" }}>
                <Prose texte={r.tsfeatures_analysis} />
              </div>
            )}
          </Card>
        )}

        {(cv.length > 0 || r.model_comparison) && (
          <Card
            title={
              <>
                <span>Modèles en concurrence</span>
                {baseline != null && (
                  <span
                    className="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[10.5px] font-semibold normal-case tracking-normal"
                    style={{ color: couleurBaseline, borderColor: couleurBaseline }}
                  >
                    {baseline ? <CheckCircle2 size={11} /> : <AlertTriangle size={11} />}
                    {baseline ? "bat SeasonalNaive" : "ne bat pas SeasonalNaive"}
                  </span>
                )}
              </>
            }
            delay={delay + 60}
          >
            {cv.map((c) => {
              const [k, v] = c.includes(":") ? [c.slice(0, c.indexOf(":")), c.slice(c.indexOf(":") + 1)] : [c, ""];
              const retenu = k.trim() === r.modele_retenu?.type;
              return (
                <div
                  key={c}
                  className="flex items-center justify-between gap-3 border-b py-1.5 text-[13px] last:border-0"
                  style={{ borderColor: "color-mix(in srgb, var(--border-muted) 50%, transparent)" }}
                >
                  <span style={{ color: retenu ? "var(--text-main)" : "var(--text-muted)", fontWeight: retenu ? 600 : 400 }}>
                    {k.trim()}
                    {retenu && <span className="ml-1.5 text-[11px] font-normal" style={{ color: "#60a5fa" }}>retenu</span>}
                  </span>
                  <span className="font-mono" style={{ color: "var(--text-main)" }}>{v.trim() || "—"}</span>
                </div>
              );
            })}
            {r.cross_validation_metric && (
              <p className="mt-2 text-[11px]" style={{ color: "var(--text-dim)" }}>
                Scores en {r.cross_validation_metric.toUpperCase()} sur validation croisée — plus bas est meilleur.
              </p>
            )}
            {r.model_comparison && (
              <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--border-muted)" }}>
                <Prose texte={r.model_comparison} />
              </div>
            )}
          </Card>
        )}
      </div>

      {(r.reason_for_selection || r.model_details || r.forecast_analysis) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {(r.reason_for_selection || r.model_details) && (
            <Card title="Pourquoi ce modèle" delay={delay + 90}>
              {r.reason_for_selection && <Prose texte={r.reason_for_selection} />}
              {r.model_details && (
                <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--border-muted)" }}>
                  <Prose texte={r.model_details} />
                </div>
              )}
            </Card>
          )}
          {(r.forecast_analysis || r.anomaly_analysis) && (
            <Card title="Lecture de la prévision" delay={delay + 120}>
              {r.forecast_analysis && <Prose texte={r.forecast_analysis} />}
              {r.anomaly_analysis && (
                <div className="mt-3 border-t pt-3" style={{ borderColor: "var(--border-muted)" }}>
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
      title={
        <>
          <span>Tableau des prévisions (IC 95%)</span>
          <button
            onClick={() => telechargerPrevisions(rows, nomModele)}
            className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-medium normal-case tracking-normal"
            style={{ borderColor: "var(--border-color)", background: "var(--bubble-ai)", color: "var(--text-main)" }}
          >
            <Download size={13} /> Télécharger (CSV)
          </button>
        </>
      }
      delay={delay}
    >
      <div className="max-h-[420px] overflow-auto rounded-md border" style={{ borderColor: "var(--border-muted)" }}>
        <table className="w-full border-collapse text-[13px]">
          <thead className="sticky top-0 z-10" style={{ background: "var(--bubble-ai)" }}>
            <tr className="text-left text-[11px] uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
              <th className="px-3.5 py-2 font-semibold">Date</th>
              <th className="px-3.5 py-2 text-right font-semibold">Prévision</th>
              <th className="px-3.5 py-2 text-right font-semibold">IC bas</th>
              <th className="px-3.5 py-2 text-right font-semibold">IC haut</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.date} className="border-t" style={{ borderColor: "color-mix(in srgb, var(--border-muted) 50%, transparent)" }}>
                <td className="whitespace-nowrap px-3.5 py-1.5" style={{ color: "var(--text-muted)" }}>{p.date}</td>
                <td className="px-3.5 py-1.5 text-right font-mono font-semibold" style={{ color: "var(--text-main)" }}>{fr(p.valeur_prevue)}</td>
                <td className="px-3.5 py-1.5 text-right font-mono" style={{ color: "var(--text-muted)" }}>{fr(p.ic_bas)}</td>
                <td className="px-3.5 py-1.5 text-right font-mono" style={{ color: "var(--text-muted)" }}>{fr(p.ic_haut)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-2.5 text-[11px]" style={{ color: "var(--text-dim)" }}>
        {rows.length} période{rows.length > 1 ? "s" : ""} prévue{rows.length > 1 ? "s" : ""}
        {avecIC ? " — intervalle de confiance à 95%." : " — aucun intervalle de confiance fourni par ce modèle."}
      </p>
    </Card>
  );
}

export default function TimeSeriesModelView({ model, onBack }: { model: ModelInfo; onBack: () => void }) {
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

  return (
    <div className="min-h-screen" style={{ background: "var(--bg-app)", color: "var(--text-main)" }}>
      <div className="mx-auto grid w-full max-w-6xl gap-6 px-5 py-8 sm:px-10">

        {/* Header */}
        <div className="flex flex-wrap items-center gap-3">
          <button onClick={onBack} className="flex items-center gap-2 rounded-md border px-4 py-2 text-[13px] font-medium transition-colors hover:bg-[var(--bubble-ai)]" style={{ borderColor: "var(--border-color)" }}>
            <ArrowLeft size={16} /> Retour
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate font-serif text-[24px] font-medium">{model.name}</h1>
            <p className="mt-0.5 flex items-center gap-2 text-[13px]" style={{ color: "var(--text-muted)" }}>
              <TrendingUp size={14} /> Modèle de série temporelle
            </p>
          </div>
          <StatutBadge statut={r.statut_final} />
        </div>

        {/* Stat tiles */}
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatTile icon={BarChart3} label="Modèle retenu" value={modelLabel} color="var(--accent)" delay={0} />
          <StatTile
            icon={Target}
            label="MAPE (out-of-sample)"
            value={r.gate_2_validation_out_of_sample?.mape_pct != null ? `${num(r.gate_2_validation_out_of_sample.mape_pct, 2)}%` : "—"}
            color="#34d399"
            delay={40}
          />
          <StatTile
            icon={Gauge}
            label="Couverture IC 95%"
            value={r.gate_2_validation_out_of_sample?.couverture_ic95_pct != null ? `${num(r.gate_2_validation_out_of_sample.couverture_ic95_pct, 1)}%` : "—"}
            color="#8b7cf6"
            delay={80}
          />
          <StatTile icon={Activity} label="AIC" value={num(modele.aic, 1)} color="#f59e0b" delay={120} />
        </div>

        {/* Forecast chart */}
        <div className="fc-fade-up rounded-lg border p-5" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)", animationDelay: "150ms" }}>
          <h3 className="mb-4 text-[12px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Historique &amp; prévision (IC 95%)</h3>
          {hasChartData ? (
            <div style={{ width: "100%", height: 360 }}>
              <ResponsiveContainer>
                <ComposedChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                  <XAxis dataKey="date" tick={{ fill: "#888", fontSize: 11 }} minTickGap={24} />
                  <YAxis tick={{ fill: "#888", fontSize: 11 }} width={56} />
                  <Tooltip
                    contentStyle={{ borderRadius: 12, border: "1px solid var(--border-color)", background: "var(--bg-panel)", color: "var(--text-main)" }}
                    formatter={(value, name) =>
                      Array.isArray(value)
                        ? [`${fr(value[0] as number)} – ${fr(value[1] as number)}`, name ?? ""]
                        : [fr(value as number), name ?? ""]
                    }
                  />
                  <Legend />
                  <Area dataKey="ic" stroke="none" fill="#8b7cf6" fillOpacity={0.15} name="Intervalle 95%" />
                  <Line type="monotone" dataKey="historique" stroke="#60a5fa" strokeWidth={2} dot={false} name="Historique" connectNulls />
                  <Line type="monotone" dataKey="prevue" stroke="#f59e0b" strokeWidth={2.5} dot={false} name="Prévision" connectNulls />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          ) : r.forecast_chart ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`data:image/png;base64,${r.forecast_chart}`} alt="Prévision" className="w-full rounded-lg" />
          ) : (
            <p className="py-10 text-center text-[13px]" style={{ color: "var(--text-dim)" }}>Aucun graphique de prévision disponible.</p>
          )}
        </div>

        {/* Tableau des prévisions, téléchargeable */}
        {(r.prevision ?? []).length > 0 && (
          <ForecastTable rows={r.prevision ?? []} nomModele={model.name} delay={185} />
        )}

        {r._engine === "timecopilot" && <TimeCopilotPanel r={r} delay={190} />}

        {r.resume_timecopilot && (
          <div className="fc-fade-up rounded-lg border p-5" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)", animationDelay: "190ms" }}>
            <h3 className="mb-3 text-[12px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>Résumé TimeCopilot</h3>
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap font-sans text-[13px]" style={{ color: "var(--text-muted)" }}>{r.resume_timecopilot}</pre>
          </div>
        )}

        {/* Gates */}
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
          <Card title={<><span>GATE 1 — Résidus</span> <GateBadge statut={r.gate_1_diagnostics_residus?.statut} /></>} delay={220}>
            <Row k="Ljung-Box (lag s)" v={num(r.gate_1_diagnostics_residus?.ljung_box_p_lag_s)} />
            <Row k="Ljung-Box (lag 2s)" v={num(r.gate_1_diagnostics_residus?.ljung_box_p_lag_2s)} />
            <Row k="Jarque-Bera (normalité)" v={num(r.gate_1_diagnostics_residus?.jarque_bera_p)} />
            <Row k="Test ARCH" v={num(r.gate_1_diagnostics_residus?.arch_p)} />
          </Card>

          <Card title={<><span>GATE 2 — Out-of-sample</span> <GateBadge statut={r.gate_2_validation_out_of_sample?.statut} /></>} delay={260}>
            <Row k="Horizon de test" v={r.gate_2_validation_out_of_sample?.horizon_test ?? "—"} />
            <Row k="MAPE (%)" v={num(r.gate_2_validation_out_of_sample?.mape_pct, 2)} />
            <Row k="RMSE" v={num(r.gate_2_validation_out_of_sample?.rmse, 2)} />
            <Row k="Couverture IC 95% (%)" v={num(r.gate_2_validation_out_of_sample?.couverture_ic95_pct, 1)} />
          </Card>

          <Card title="Modèle retenu" delay={300}>
            <Row k="Type" v={modele.type ?? "—"} />
            <Row k="Ordre (p,d,q)" v={ordre} />
            <Row k="Ordre saisonnier (P,D,Q,s)" v={ordreSais} />
            <Row k="AIC" v={num(modele.aic, 2)} />
            <Row k="BIC" v={num(modele.bic, 2)} />
            {modele.coefficients && modele.coefficients.length > 0 && (
              <div className="mt-3 border-t pt-2" style={{ borderColor: "var(--border-muted)" }}>
                <div className="mb-1 text-[11px]" style={{ color: "var(--text-dim)" }}>Coefficients</div>
                {modele.coefficients.map((c) => (
                  <Row key={c.nom} k={c.nom} v={`${num(c.valeur)} (p=${num(c.p_value)})`} />
                ))}
              </div>
            )}
          </Card>

          <Card title="Série & stationnarité" delay={340}>
            <Row k="Observations" v={r.serie?.n_observations ?? "—"} />
            <Row k="Fréquence" v={r.serie?.frequence ?? "—"} />
            <Row k="Saisonnalité détectée" v={r.serie?.saisonnalite_detectee ?? "—"} />
            <Row k="Différenciation d / D" v={`${r.stationnarite?.d ?? "—"} / ${r.stationnarite?.D ?? "—"}`} />
            <Row k="ADF p-value (finale)" v={num(r.stationnarite?.adf_p_value_finale)} />
            <Row k="KPSS p-value (finale)" v={num(r.stationnarite?.kpss_p_value_finale)} />
            <Row k="Log appliqué" v={r.transformation?.log_applique ? "oui" : "non"} />
          </Card>
        </div>

        {r.avertissements && r.avertissements.length > 0 && (
          <div className="fc-fade-up rounded-lg border p-5" style={{ borderColor: "#f59e0b", background: "rgba(245,158,11,0.08)", animationDelay: "380ms" }}>
            <h3 className="mb-2 flex items-center gap-2 text-[13px] font-semibold" style={{ color: "#f59e0b" }}><AlertTriangle size={15} /> Avertissements</h3>
            <ul className="list-inside list-disc space-y-1 text-[13px]" style={{ color: "var(--text-muted)" }}>
              {r.avertissements.map((a, i) => <li key={i}>{a}</li>)}
            </ul>
          </div>
        )}

        <div className="pt-1 text-center text-[11px]" style={{ color: "var(--text-dim)" }}>
          Créé le {new Date(model.created_at).toLocaleString("fr-FR")}
        </div>
      </div>
    </div>
  );
}
