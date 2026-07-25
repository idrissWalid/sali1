"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  AudioLines,
  BrainCircuit,
  FileText,
  FolderOpen,
  LayoutDashboard,
  LineChart,
  Loader2,
} from "lucide-react";
import { useEffect, useState } from "react";
import { API_URL, downloadReport } from "../lib/api";
import Modal from "./Modal";

interface Props {
  sessionId: string | null;
  generatedContent?: string;
  openModels?: () => void;
  chatModelPending?: boolean;
  modelsRefreshKey?: number;
}

interface TrainedModel {
  id: string;
  name: string;
  type: string;
  created_at: string;
}

type ReportFormat = "pdf" | "word" | null;
type TrainingType = "classification" | "regression" | "prediction" | "timeseries" | null;

interface TsCandidates {
  date_columns: string[];
  value_columns: string[];
  feasible: boolean;
}

interface GeneratedItem {
  id: string;
  title: string;
  kind: "report" | "model";
  format?: ReportFormat;
  url?: string;
}

interface ModelFeasibility {
  classification: boolean;
  regression: boolean;
  prediction: boolean;
}

const NO_FEASIBILITY: ModelFeasibility = { classification: false, regression: false, prediction: false };

// Estime, à partir du profil ydata-profiling sauvegardé pour la session,
// quels types de modèles ont une chance raisonnable de fonctionner sur ce
// jeu de données (sans lancer d'entraînement réel).
function computeModelFeasibility(sessionType: string | null, profile: Record<string, unknown> | null, stats: Record<string, unknown> | null): ModelFeasibility {
  if (sessionType !== "tabular" || !profile || !stats) return NO_FEASIBILITY;

  const rows = typeof profile.rows === "number" ? profile.rows : 0;
  const variables = (stats.variables as Record<string, { type?: string; n_valeurs_distinctes?: number }>) || {};

  let numericCols = 0;
  let categoricalTargets = 0;
  for (const v of Object.values(variables)) {
    if (v.type === "Numeric") {
      numericCols++;
    } else if (
      (v.type === "Categorical" || v.type === "Boolean") &&
      typeof v.n_valeurs_distinctes === "number" &&
      v.n_valeurs_distinctes >= 2 &&
      v.n_valeurs_distinctes <= 20
    ) {
      categoricalTargets++;
    }
  }

  const enoughRows = rows >= 20;
  const classification = enoughRows && categoricalTargets >= 1 && numericCols + categoricalTargets >= 2;
  const regression = enoughRows && numericCols >= 2;

  return { classification, regression, prediction: classification || regression };
}

const REPORT_PLACEHOLDERS = [
  "Ex. tendances, anomalies, recommandations...",
  "Ex. points clés à expliquer au lecteur...",
  "Ex. observations importantes à mettre en avant...",
];

const SOON_ITEMS = [
  { icon: AudioLines, label: "Résumé audio" },
  { icon: FolderOpen, label: "Fiches synthèse" },
];

function Tile({
  icon: Icon,
  label,
  onClick,
  disabled,
  title,
  soon,
  span2,
}: {
  icon: typeof LayoutDashboard;
  label: string;
  onClick?: () => void;
  disabled?: boolean;
  title?: string;
  soon?: boolean;
  span2?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`relative flex min-h-[92px] flex-col justify-between rounded-lg border p-4 text-left transition-all ${span2 ? "col-span-2" : ""} ${disabled ? "cursor-not-allowed opacity-50" : "hover:border-[var(--accent)] hover:bg-[var(--bubble-ai)]"}`}
      style={{ background: "var(--bubble-ai)", borderColor: "var(--border-color)" }}
    >
      {soon && (
        <span className="absolute right-2.5 top-2.5 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide" style={{ background: "var(--border-color)", color: "var(--text-muted)" }}>
          Bientôt
        </span>
      )}
      <Icon size={22} strokeWidth={1.7} style={{ color: soon ? "var(--text-muted)" : "var(--accent)" }} />
      <div className="mt-2.5 text-[13px] font-medium leading-tight" style={{ color: soon ? "var(--text-muted)" : "var(--text-main)" }}>
        {label}
      </div>
    </button>
  );
}

export default function StudioPanel({ sessionId, generatedContent, openModels, chatModelPending = false, modelsRefreshKey = 0 }: Props) {
  const [isReportOpen, setIsReportOpen] = useState(false);
  const [isTrainingOpen, setIsTrainingOpen] = useState(false);
  const [reportFormat, setReportFormat] = useState<ReportFormat>(null);
  const [reportKeyPoints, setReportKeyPoints] = useState("");
  const [trainingType, setTrainingType] = useState<TrainingType>(null);
  const [trainingName, setTrainingName] = useState("");
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  const [items, setItems] = useState<GeneratedItem[]>([]);
  const [trainedModels, setTrainedModels] = useState<TrainedModel[]>([]);
  const [modalTraining, setModalTraining] = useState(false);
  const [feasibility, setFeasibility] = useState<ModelFeasibility>(NO_FEASIBILITY);
  const [tsCandidates, setTsCandidates] = useState<TsCandidates>({ date_columns: [], value_columns: [], feasible: false });
  const [tsDateCol, setTsDateCol] = useState("");
  const [tsValueCol, setTsValueCol] = useState("");
  const [tsHorizon, setTsHorizon] = useState("12");
  const [tsEngine, setTsEngine] = useState<"auto" | "timecopilot">("timecopilot");
  const [isTrainingModel, setIsTrainingModel] = useState(false);
  const anyModelPossible = feasibility.classification || feasibility.regression || feasibility.prediction || tsCandidates.feasible;

  useEffect(() => {
    const id = setInterval(() => setPlaceholderIdx((p) => (p + 1) % REPORT_PLACEHOLDERS.length), 3000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => setItems([]), [sessionId]);

  const refetchModels = async () => {
    if (!sessionId) return;
    try {
      const res = await fetch(`${API_URL}/api/models/${sessionId}`);
      if (res.ok) {
        const d = await res.json();
        setTrainedModels(d.models || []);
      }
    } catch {
      /* ignore */
    }
  };

  // Liste réelle des modèles de la session, rechargée quand la session change
  // ou quand le parent incrémente modelsRefreshKey (chat vient de générer).
  useEffect(() => {
    if (!sessionId) {
      setTrainedModels([]);
      return;
    }
    let cancelled = false;
    fetch(`${API_URL}/api/models/${sessionId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setTrainedModels(data.models || []);
      })
      .catch(() => {
        if (!cancelled) setTrainedModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, modelsRefreshKey]);

  // Détermine quels types de modèles sont proposables pour le dataset de la
  // session courante (sans lancer d'entraînement réel).
  useEffect(() => {
    if (!sessionId) {
      setFeasibility(NO_FEASIBILITY);
      return;
    }
    let cancelled = false;
    fetch(`${API_URL}/api/sessions/${sessionId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setFeasibility(computeModelFeasibility(data.type ?? null, data.data_profile ?? null, data.data_stats ?? null));
      })
      .catch(() => {
        if (!cancelled) setFeasibility(NO_FEASIBILITY);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Colonnes candidates pour une série temporelle (axe date + valeur numérique).
  useEffect(() => {
    if (!sessionId) {
      setTsCandidates({ date_columns: [], value_columns: [], feasible: false });
      return;
    }
    let cancelled = false;
    fetch(`${API_URL}/api/models/timeseries-candidates/${sessionId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setTsCandidates({ date_columns: data.date_columns || [], value_columns: data.value_columns || [], feasible: !!data.feasible });
      })
      .catch(() => {
        if (!cancelled) setTsCandidates({ date_columns: [], value_columns: [], feasible: false });
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const addItem = (item: GeneratedItem) => setItems((prev) => [item, ...prev]);

  const handleReportSubmit = async () => {
    if (!sessionId || !reportFormat) return;
    setIsGeneratingReport(true);
    try {
      const title = reportKeyPoints.trim()
        ? `Rapport d'analyse de données — ${reportKeyPoints.trim().slice(0, 80)}`
        : "Rapport d'analyse de données";
      const blob = await downloadReport(sessionId, reportFormat, title);
      const url = URL.createObjectURL(blob);
      addItem({
        id: `${Date.now()}-${reportFormat}`,
        title: reportKeyPoints.trim() ? `Rapport • ${reportKeyPoints.trim().slice(0, 40)}` : `Rapport d'analyse (${reportFormat.toUpperCase()})`,
        kind: "report",
        format: reportFormat,
        url,
      });
      const a = document.createElement("a");
      a.href = url;
      a.download = reportFormat === "pdf" ? "rapport_analyse.pdf" : "rapport_analyse.docx";
      a.click();
      window.open(url, "_blank", "noopener,noreferrer");
      setIsReportOpen(false);
    } catch {
      alert("Erreur lors de la génération du rapport.");
    } finally {
      setIsGeneratingReport(false);
    }
  };

  const handleTrainingSubmit = async () => {
    if (!trainingType) return;

    // ── Séries temporelles : entraînement réel (ARIMA complet / Modèles auto) ──
    if (trainingType === "timeseries") {
      if (!sessionId || !tsDateCol || !tsValueCol) return;
      // Ferme la modale et affiche un placeholder animé dans « Éléments générés ».
      setIsTrainingOpen(false);
      setModalTraining(true);
      try {
        const model = typeof window !== "undefined" ? localStorage.getItem("selected_model") || undefined : undefined;
        const res = await fetch(`${API_URL}/api/models/train-timeseries`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            date_col: tsDateCol,
            value_col: tsValueCol,
            horizon: parseInt(tsHorizon) || undefined,
            engine: tsEngine,
            model,
          }),
        });
        if (!res.ok) {
          const data = await res.json().catch(() => null);
          throw new Error(data?.detail || "Échec de l'entraînement.");
        }
        // Modèle persisté : on recharge la liste → il apparaît, cliquable.
        await refetchModels();
      } catch (err) {
        alert(err instanceof Error ? err.message : "Erreur lors de l'entraînement.");
      } finally {
        setModalTraining(false);
      }
      return;
    }

    // ── Autres types : encore simulés ──
    if (!trainingName.trim()) return;
    addItem({ id: `model-${Date.now()}`, title: trainingName.trim(), kind: "model" });
    openModels?.();
    setIsTrainingOpen(false);
  };

  return (
    <>
      <div className="flex h-full flex-col overflow-hidden rounded-lg border" style={{ background: "var(--bg-panel)", borderColor: "var(--border-color)" }}>
        <div className="shrink-0 border-b px-5 py-4 font-serif text-[16px] font-medium" style={{ borderColor: "var(--border-color)", color: "var(--text-main)" }}>
          Studio
        </div>

        <div className="grid shrink-0 grid-cols-2 gap-2.5 p-4">
          <Tile icon={LayoutDashboard} label="Dashboard interactif" disabled={!sessionId} onClick={() => sessionId && window.open(`/dashboard/${sessionId}`, "_blank")} />
          <Tile icon={FileText} label="Générer un rapport" onClick={() => { setReportFormat(null); setReportKeyPoints(""); setIsReportOpen(true); }} />
          {SOON_ITEMS.map((it) => (
            <Tile key={it.label} icon={it.icon} label={it.label} disabled soon />
          ))}
          <Tile
            icon={BrainCircuit}
            label="Entraîner un modèle — créer et suivre vos modèles prédictifs"
            span2
            disabled={!sessionId || !anyModelPossible}
            title={!sessionId ? "Chargez d'abord un jeu de données." : !anyModelPossible ? "Aucun modèle n'est compatible avec ce jeu de données." : undefined}
            onClick={() => { setTrainingType(null); setTrainingName(""); setTsDateCol(tsCandidates.date_columns[0] ?? ""); setTsValueCol(tsCandidates.value_columns[0] ?? ""); setTsEngine("auto"); setIsTrainingOpen(true); }}
          />
        </div>

        <div className="flex min-h-0 flex-1 flex-col border-t" style={{ borderColor: "var(--border-color)", background: "color-mix(in srgb, var(--bg-chat) 40%, transparent)" }}>
          <div className="flex shrink-0 items-center justify-between px-5 py-4">
            <div>
              <div className="text-[13px] font-semibold" style={{ color: "var(--text-main)" }}>Éléments générés</div>
              <div className="mt-0.5 text-[11px]" style={{ color: "var(--text-muted)" }}>Rapports, modèles et résultats de cette session</div>
            </div>
            {sessionId && <span className="size-1.5 rounded-full" style={{ background: "var(--accent)", boxShadow: "0 0 0 4px var(--accent-soft)" }} />}
          </div>

          <div className="flex flex-col gap-2 overflow-y-auto px-4 pb-4">
            {/* Placeholder animé : un modèle est en cours de génération. */}
            {(chatModelPending || modalTraining) && (
              <div
                className="flex items-center gap-2.5 rounded-md border px-3 py-3"
                style={{ borderColor: "var(--accent)", background: "var(--accent-soft)" }}
              >
                <Loader2 size={16} className="animate-spin" style={{ color: "var(--accent)" }} />
                <span className="flex-1">
                  <div className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Génération du modèle en cours…</div>
                  <div className="mt-0.5 text-[10px]" style={{ color: "var(--text-muted)" }}>Cela peut prendre jusqu’à ~2 minutes</div>
                </span>
              </div>
            )}

            {/* Modèles réels de la session (chat + modale) — cliquables. */}
            {trainedModels.map((m) => (
              <button
                key={m.id}
                onClick={() => window.open(`/dashboard/model/${m.id}`, "_blank")}
                className="flex items-center justify-between gap-2.5 rounded-md border px-3 py-3 text-left transition-colors hover:border-[var(--accent)]"
                style={{ borderColor: "var(--border-muted)", background: "var(--bubble-ai)" }}
              >
                <span className="grid size-7 shrink-0 place-items-center rounded-md" style={{ color: "var(--accent)", background: "var(--accent-soft)" }}>
                  {m.type === "timeseries" ? <LineChart size={15} strokeWidth={1.8} /> : <BrainCircuit size={15} strokeWidth={1.8} />}
                </span>
                <span className="min-w-0 flex-1">
                  <div className="truncate text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>{m.name}</div>
                  <div className="mt-0.5 text-[10px]" style={{ color: "var(--text-muted)" }}>
                    {m.type === "timeseries" ? "Modèle • Série temporelle" : "Modèle"}
                  </div>
                </span>
                <span className="shrink-0 text-[10px] font-bold" style={{ color: "var(--accent)" }}>Dashboard</span>
              </button>
            ))}

            {/* Rapports générés (client). */}
            {items.filter((it) => it.kind === "report").map((item) => (
              <button
                key={item.id}
                onClick={() => item.url && window.open(item.url, "_blank", "noopener,noreferrer")}
                className="flex items-center justify-between gap-2.5 rounded-md border px-3 py-3 text-left transition-colors hover:border-[var(--accent)]"
                style={{ borderColor: "var(--border-muted)", background: "var(--bubble-ai)" }}
              >
                <span className="flex-1">
                  <div className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>{item.title}</div>
                  <div className="mt-0.5 text-[10px]" style={{ color: "var(--text-muted)" }}>
                    {`Rapport • ${item.format?.toUpperCase()}`}
                  </div>
                </span>
                <span className="text-[10px] font-bold" style={{ color: "var(--accent)" }}>Ouvrir</span>
              </button>
            ))}

            {!chatModelPending && !modalTraining && trainedModels.length === 0 && items.filter((it) => it.kind === "report").length === 0 && !generatedContent && (
              <div className="px-1 py-2 text-[12px]" style={{ color: "var(--text-dim)" }}>
                Aucun élément généré pour l’instant. Générez un rapport ou entraînez un modèle.
              </div>
            )}

            {generatedContent && (
              <div className="rounded-md border p-3.5" style={{ borderColor: "var(--border-muted)", background: "var(--bubble-ai)" }}>
                <div className="mb-2 text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Dernier résultat</div>
                <div className="max-h-[120px] overflow-y-auto whitespace-pre-wrap text-[12px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
                  {generatedContent}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <Modal isOpen={isReportOpen} onClose={() => setIsReportOpen(false)} title="Générer un rapport" maxWidth="520px">
        <div className="flex flex-col gap-4">
          <p className="text-[13px]" style={{ color: "var(--text-muted)" }}>Vous pouvez laisser la description vide et générer directement le rapport.</p>
          <div className="relative">
            <textarea
              value={reportKeyPoints}
              onChange={(e) => setReportKeyPoints(e.target.value)}
              className="w-full resize-y rounded-md border px-3.5 py-3 text-[13px] outline-none"
              style={{ minHeight: 110, borderColor: "var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }}
            />
            {!reportKeyPoints.trim() && (
              <div className="pointer-events-none absolute inset-x-3.5 top-3">
                <AnimatePresence mode="wait">
                  <motion.div key={placeholderIdx} initial={{ y: 6, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -10, opacity: 0 }} transition={{ duration: 0.22 }} className="text-[13px]" style={{ color: "var(--text-muted)" }}>
                    {REPORT_PLACEHOLDERS[placeholderIdx]}
                  </motion.div>
                </AnimatePresence>
              </div>
            )}
          </div>
          <div className="flex flex-col gap-2">
            <div className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Choisir le format</div>
            <div className="flex gap-2.5">
              {(["pdf", "word"] as const).map((fmt) => (
                <button
                  key={fmt}
                  onClick={() => setReportFormat(fmt)}
                  className="flex-1 rounded-md border py-2.5 text-[13px] font-semibold uppercase"
                  style={{
                    borderColor: reportFormat === fmt ? "var(--accent)" : "var(--border-muted)",
                    background: reportFormat === fmt ? "var(--accent-soft)" : "var(--bubble-ai)",
                    color: "var(--text-main)",
                  }}
                >
                  {fmt}
                </button>
              ))}
            </div>
          </div>
          <button
            onClick={handleReportSubmit}
            disabled={!sessionId || !reportFormat || isGeneratingReport}
            className="rounded-md py-2.5 text-[13px] font-bold text-white disabled:cursor-not-allowed disabled:opacity-50"
            style={{ background: "var(--accent)" }}
          >
            {isGeneratingReport ? "Génération en cours..." : "Générer"}
          </button>
        </div>
      </Modal>

      <Modal isOpen={isTrainingOpen} onClose={() => setIsTrainingOpen(false)} title="Entraîner un modèle" maxWidth="520px">
        <div className="flex flex-col gap-4">
          <p className="text-[13px]" style={{ color: "var(--text-muted)" }}>Choisissez un type de modèle et donnez-lui un nom avant de lancer l&rsquo;entraînement.</p>
          <div className="flex flex-col gap-1.5">
            <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Type de modèle</label>
            <div className="flex flex-wrap gap-2">
              {(
                [
                  { id: "classification" as const, label: "Classification", possible: feasibility.classification },
                  { id: "regression" as const, label: "Régression", possible: feasibility.regression },
                  { id: "prediction" as const, label: "Prédiction", possible: feasibility.prediction },
                  { id: "timeseries" as const, label: "Séries temporelles", possible: tsCandidates.feasible },
                ]
              ).map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  disabled={!opt.possible}
                  onClick={() => setTrainingType(opt.id)}
                  title={opt.possible ? undefined : "Ce jeu de données n'a pas les colonnes nécessaires pour ce type de modèle."}
                  className="rounded-md border py-2.5 text-[13px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40"
                  style={{
                    flex: "1 1 45%",
                    borderColor: trainingType === opt.id ? "var(--accent)" : "var(--border-muted)",
                    background: trainingType === opt.id ? "var(--accent-soft)" : "var(--bubble-ai)",
                    color: "var(--text-main)",
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {!anyModelPossible && (
              <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                Aucun type de modèle n&rsquo;est compatible avec ce jeu de données (il faut par exemple au moins 20 lignes et plusieurs colonnes numériques ou catégorielles adaptées).
              </p>
            )}
          </div>

          {trainingType === "timeseries" ? (
            <>
              <div className="flex gap-2.5">
                <div className="flex flex-1 flex-col gap-1.5">
                  <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Colonne date</label>
                  <select value={tsDateCol} onChange={(e) => setTsDateCol(e.target.value)} className="rounded-md border px-3 py-2.5 text-[13px]" style={{ borderColor: "var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }}>
                    {tsCandidates.date_columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div className="flex flex-1 flex-col gap-1.5">
                  <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Colonne valeur</label>
                  <select value={tsValueCol} onChange={(e) => setTsValueCol(e.target.value)} className="rounded-md border px-3 py-2.5 text-[13px]" style={{ borderColor: "var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }}>
                    {tsCandidates.value_columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>
              <div className="flex gap-2.5">
                <div className="flex flex-1 flex-col gap-1.5">
                  <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Horizon (périodes)</label>
                  <input type="number" min={1} value={tsHorizon} onChange={(e) => setTsHorizon(e.target.value)} className="rounded-md border px-3 py-2.5 text-[13px]" style={{ borderColor: "var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }} />
                </div>
                <div className="flex flex-1 flex-col gap-1.5">
                  <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Moteur</label>
                  <select value={tsEngine} onChange={(e) => setTsEngine(e.target.value as "auto" | "timecopilot")} className="rounded-md border px-3 py-2.5 text-[13px]" style={{ borderColor: "var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }}>
                    <option value="timecopilot">Modèles auto</option>
                    <option value="auto">ARIMA complet</option>
                  </select>
                </div>
              </div>
              <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                « Modèles auto » met plusieurs modèles en concurrence et explique son choix. « ARIMA complet » suit la méthodologie détaillée (stationnarité, sélection, diagnostics des résidus, validation out-of-sample). Comptez jusqu&rsquo;à ~2 minutes.
              </p>
            </>
          ) : (
            <div className="flex flex-col gap-1.5">
              <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Nom du modèle</label>
              <input
                value={trainingName}
                onChange={(e) => setTrainingName(e.target.value)}
                placeholder="Ex. modèle_vente_2026"
                className="rounded-md border px-3.5 py-2.5 text-[13px]"
                style={{ borderColor: "var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }}
              />
            </div>
          )}
          <button
            onClick={handleTrainingSubmit}
            disabled={!trainingType || isTrainingModel || (trainingType === "timeseries" ? (!tsDateCol || !tsValueCol) : !trainingName.trim())}
            className="rounded-md py-2.5 text-[13px] font-bold text-white disabled:cursor-not-allowed disabled:opacity-50"
            style={{ background: "var(--accent)" }}
          >
            {isTrainingModel ? (trainingType === "timeseries" ? "Entraînement en cours…" : "Ouverture...") : "Entraîner"}
          </button>
        </div>
      </Modal>
    </>
  );
}
