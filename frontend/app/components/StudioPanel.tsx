"use client";
import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AudioLines, BrainCircuit, FileText, LayoutDashboard, Loader2, LineChart, Presentation } from "lucide-react";
import Modal from "./Modal";
import GlareHover from './GlareHover';
import { API_URL } from "@/lib/api";

interface Props {
  sessionId: string | null;
  generatedContent?: string;
  // Un modèle est en cours de génération dans le chat → placeholder animé.
  chatModelPending?: boolean;
  // Incrémenté par le parent pour forcer un rechargement de la liste des modèles
  // (ex: quand le chat vient de terminer la génération d'un modèle).
  modelsRefreshKey?: number;
}

interface TrainedModel {
  id: string;
  name: string;
  type: string;
  created_at: string;
}

const STUDIO_ITEMS_SOON = [
  {
    icon: (
      <span style={{ display: "inline-flex", alignItems: "center" }}>
        <AudioLines size={22} strokeWidth={1.8} />
      </span>
    ), label: "Résumé audio"
  },
];

type ReportFormat = "pdf" | "word" | "powerpoint" | null;

// Libellé, extension et intitulé de chaque format proposé par la modale. Les
// extensions doivent suivre celles servies par /api/report : c'est ce nom que
// le navigateur écrit sur le disque.
const FORMATS_RAPPORT = [
  { id: "pdf" as const, label: "PDF", fichier: "rapport_analyse.pdf" },
  { id: "word" as const, label: "Word", fichier: "rapport_analyse.docx" },
  { id: "powerpoint" as const, label: "PowerPoint", fichier: "rapport_analyse.pptx" },
];
type TrainingType = "predictif" | "timeseries" | null;
type TimeSeriesEngine = "timecopilot" | "autoforecast";

/** Verdict du backend sur le modèle LLM sélectionné, obtenu AVANT tout lancement :
 *  TimeCopilot pilote sa prévision par appels d'outils, qu'un petit modèle local
 *  ne sait pas produire. Le savoir avant évite d'attendre plusieurs minutes pour
 *  se voir refuser. */
interface EngineInfo {
  tool_use: boolean;
  timecopilot_installe: boolean;
  engine: TimeSeriesEngine;
  avertissement: string | null;
  message_repli: string | null;
}

/** Colonnes proposées par le LLM, et son motif. `colonne` (supervisé) ou le
 *  couple date/valeur (séries) valent null si aucune proposition exploitable. */
interface Proposition {
  colonne?: string | null;
  date?: string | null;
  valeur?: string | null;
  motif?: string;
}

const FAMILLES_LABEL: Record<string, string> = {
  regression: "Régression",
  classification: "Classification",
  classification_desequilibree: "Classification déséquilibrée",
};

/** Cible possible et famille qui en découlerait. L'utilisateur choisit QUOI
 *  prédire ; le moteur déduit la famille et met ses modèles en concurrence. */
interface CibleSupervisee {
  colonne: string;
  famille: string;
  n_modalites: number;
  ratio_minoritaire: number | null;
}

interface TsCandidates {
  date_columns: string[];
  value_columns: string[];
  feasible: boolean;
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

type GeneratedItem = {
  id: string;
  title: string;
  kind: "report" | "model";
  format?: ReportFormat;
  url?: string;
};

const REPORT_PLACEHOLDERS = [
  "Ex. tendances, anomalies, recommandations...",
  "Ex. points clés à expliquer au lecteur...",
  "Ex. observations importantes à mettre en avant...",
];

export default function StudioPanel({ sessionId, generatedContent, chatModelPending = false, modelsRefreshKey = 0 }: Props) {
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);
  const [isTrainingModalOpen, setIsTrainingModalOpen] = useState(false);
  const [reportFormat, setReportFormat] = useState<ReportFormat>(null);
  const [reportKeyPoints, setReportKeyPoints] = useState("");
  const [trainingType, setTrainingType] = useState<TrainingType>(null);
  const [supCibles, setSupCibles] = useState<CibleSupervisee[]>([]);
  const [supTarget, setSupTarget] = useState("");
  const cibleChoisie = supCibles.find((c) => c.colonne === supTarget) ?? null;
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const [generatedItems, setGeneratedItems] = useState<GeneratedItem[]>([]);
  // Vrais modèles entraînés de la session (source de vérité côté backend).
  const [trainedModels, setTrainedModels] = useState<TrainedModel[]>([]);
  // Placeholder animé pendant un entraînement lancé depuis la modale.
  const [modalTraining, setModalTraining] = useState(false);
  const [feasibility, setFeasibility] = useState<ModelFeasibility>(NO_FEASIBILITY);
  // Séries temporelles : colonnes candidates + sélection utilisateur.
  const [tsCandidates, setTsCandidates] = useState<TsCandidates>({ date_columns: [], value_columns: [], feasible: false });
  const [tsDateCol, setTsDateCol] = useState("");
  const [tsValueCol, setTsValueCol] = useState("");
  const [tsHorizon, setTsHorizon] = useState("12");
  // Moteur réellement exécuté, décidé par le backend selon le modèle LLM choisi
  // (voir /models/timeseries-engine) : TimeCopilot, ou AutoForecast en repli.
  const [tsEngine, setTsEngine] = useState<TimeSeriesEngine>("timecopilot");
  const [engineInfo, setEngineInfo] = useState<EngineInfo | null>(null);
  // L'utilisateur a accepté le repli malgré l'avertissement.
  const [repliAccepte, setRepliAccepte] = useState(false);
  // Proposition du LLM (présélection argumentée, jamais une décision).
  const [proposition, setProposition] = useState<Proposition | null>(null);
  const [propositionEnCours, setPropositionEnCours] = useState(false);
  const anyModelPossible = feasibility.classification || feasibility.regression || feasibility.prediction || tsCandidates.feasible;

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setPlaceholderIndex((prev) => (prev + 1) % REPORT_PLACEHOLDERS.length);
    }, 3000);

    return () => window.clearInterval(intervalId);
  }, []);

  // Tous les états dérivés de la session sont purgés dès que celle-ci change,
  // pendant le rendu (motif React documenté). Le faire depuis des effets
  // affichait un instant les éléments de la session précédente et provoquait
  // autant de rendus en cascade.
  const [sessionPrecedente, setSessionPrecedente] = useState(sessionId);
  if (sessionId !== sessionPrecedente) {
    setSessionPrecedente(sessionId);
    setGeneratedItems([]);
    if (!sessionId) {
      setTrainedModels([]);
      setFeasibility(NO_FEASIBILITY);
      setTsCandidates({ date_columns: [], value_columns: [], feasible: false });
      setSupCibles([]);
    }
  }

  // Charge (et recharge) la liste réelle des modèles de la session. Rechargée
  // quand la session change OU quand le parent incrémente modelsRefreshKey
  // (ex: le chat vient de terminer la génération d'un modèle).
  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let cancelled = false;
    const apiUrl = API_URL;
    fetch(`${apiUrl}/api/models/${sessionId}`)
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
      return;
    }
    let cancelled = false;
    const apiUrl = API_URL;
    fetch(`${apiUrl}/api/sessions/${sessionId}`)
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

  // Cibles possibles pour un modèle prédictif, avec la famille annoncée avant
  // de lancer un tournoi qui peut durer plusieurs minutes.
  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let cancelled = false;
    const apiUrl = API_URL;
    fetch(`${apiUrl}/api/models/supervised-candidates/${sessionId}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        setSupCibles(data.cibles || []);
      })
      .catch(() => {
        if (!cancelled) setSupCibles([]);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Colonnes candidates pour une série temporelle (axe date + valeur numérique).
  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let cancelled = false;
    const apiUrl = API_URL;
    fetch(`${apiUrl}/api/models/timeseries-candidates/${sessionId}`)
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

  const addGeneratedItem = (item: GeneratedItem) => {
    setGeneratedItems((prev) => [item, ...prev]);
  };

  const openGeneratedItem = (item: GeneratedItem) => {
    if (item.url) {
      window.open(item.url, "_blank", "noopener,noreferrer");
    }
  };

  const downloadReport = async (format: "pdf" | "word" | "powerpoint", keyPoints = "") => {
    if (!sessionId) {
      alert("Aucune session active. Chargez d'abord un fichier.");
      return;
    }
    const descripteur = FORMATS_RAPPORT.find((f) => f.id === format)!;
    try {
      const apiUrl = API_URL;
      const model = typeof window !== "undefined" ? localStorage.getItem("selected_model") || undefined : undefined;
      const res = await fetch(`${apiUrl}/api/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          // Le titre reste le titre : les points clés sont une consigne de
          // rédaction, transmise comme telle et non collée à la page de garde.
          title: "Rapport d'analyse de données",
          institution: "CITADEL — Ouagadougou, Burkina Faso",
          format,
          key_points: keyPoints.trim(),
          model,
        }),
      });
      if (!res.ok) {
        // Le backend explique désormais pourquoi la rédaction a échoué ; le
        // message générique laissait l'utilisateur sans piste.
        const detail = await res.json().catch(() => null);
        throw new Error(detail?.detail || "Erreur serveur");
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      addGeneratedItem({
        id: `${Date.now()}-${format}`,
        title: keyPoints.trim() ? `Rapport • ${keyPoints.trim().slice(0, 40)}` : `Rapport d'analyse (${descripteur.label})`,
        kind: "report",
        format,
        url,
      });
      const a = document.createElement("a");
      a.href = url;
      a.download = descripteur.fichier;
      a.click();
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      alert(e instanceof Error ? e.message : "Erreur lors de la génération du rapport.");
    }
  };

  const refetchModels = async () => {
    if (!sessionId) return;
    const apiUrl = API_URL;
    try {
      const res = await fetch(`${apiUrl}/api/models/${sessionId}`);
      if (res.ok) {
        const d = await res.json();
        setTrainedModels(d.models || []);
      }
    } catch {
      /* ignore */
    }
  };

  const openModelDashboard = (id: string) => {
    window.open(`/dashboard/model/${id}`, "_blank");
  };

  // `formatInitial` permet d'entrer dans la modale depuis une carte qui nomme
  // déjà son format : le choix est alors présélectionné, sans empêcher d'en
  // changer une fois la modale ouverte.
  const openReportModal = (formatInitial: ReportFormat = null) => {
    setReportFormat(formatInitial);
    setReportKeyPoints("");
    setIsReportModalOpen(true);
  };

  const openTrainingModal = () => {
    setTrainingType(null);
    // Présélections de repli, remplacées par la proposition du LLM dès qu'un type
    // d'entraînement est choisi. `candidates[0]` n'est que l'ordre du fichier :
    // sur un CSV qui commence par « id », cela proposait « id » comme cible.
    setSupTarget(supCibles[0]?.colonne ?? "");
    setTsDateCol(tsCandidates.date_columns[0] ?? "");
    setTsValueCol(tsCandidates.value_columns[0] ?? "");
    setTsEngine("timecopilot");
    setEngineInfo(null);
    setRepliAccepte(false);
    setProposition(null);
    setIsTrainingModalOpen(true);
  };

  const handleReportSubmit = async () => {
    if (!sessionId || !reportFormat) return;
    setIsGeneratingReport(true);
    try {
      await downloadReport(reportFormat, reportKeyPoints);
      setIsReportModalOpen(false);
    } finally {
      setIsGeneratingReport(false);
    }
  };

  /** Choix du type d'entraînement. Les états dérivés sont remis à zéro ici, dans
   *  le gestionnaire d'événement, et non dans l'effet qui suit : y appeler
   *  setState de façon synchrone déclenche des rendus en cascade. */
  const choisirTypeEntrainement = (type: Exclude<TrainingType, null>) => {
    setTrainingType(type);
    setProposition(null);
    setPropositionEnCours(true);
    setEngineInfo(null);
    setRepliAccepte(false);
  };

  // Dès qu'un type d'entraînement est choisi dans la modale : on demande au LLM
  // quelles colonnes modéliser, et — pour les séries — quel moteur tournera
  // réellement. Les deux appels sont faits ici, pas à l'ouverture, car ils
  // dépendent du type choisi.
  useEffect(() => {
    if (!isTrainingModalOpen || !trainingType || !sessionId) return;
    let annule = false;
    const model = typeof window !== "undefined" ? localStorage.getItem("selected_model") || undefined : undefined;

    if (trainingType === "timeseries") {
      const params = new URLSearchParams(model ? { model } : {});
      fetch(`${API_URL}/api/models/timeseries-engine?${params}`)
        .then((res) => (res.ok ? res.json() : null))
        .then((info: EngineInfo | null) => {
          if (annule || !info) return;
          setEngineInfo(info);
          setTsEngine(info.engine);
        })
        .catch(() => { /* le backend tranchera de toute façon au lancement */ });
    }

    fetch(`${API_URL}/api/models/propose-variables`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        kind: trainingType === "timeseries" ? "timeseries" : "supervised",
        model,
      }),
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data: Proposition | null) => {
        if (annule || !data) return;
        setProposition(data);
        // Présélection seulement : les sélecteurs restent pleinement modifiables.
        if (trainingType === "timeseries") {
          if (data.date) setTsDateCol(data.date);
          if (data.valeur) setTsValueCol(data.valeur);
        } else if (data.colonne) {
          setSupTarget(data.colonne);
        }
      })
      .catch(() => { /* sans proposition, les présélections de repli tiennent */ })
      .finally(() => { if (!annule) setPropositionEnCours(false); });

    return () => { annule = true; };
  }, [isTrainingModalOpen, trainingType, sessionId]);

  const handleTrainingSubmit = async () => {
    if (!trainingType) return;

    // ── Séries temporelles : entraînement réel (ARIMA complet / Modèles auto) ──
    if (trainingType === "timeseries") {
      if (!sessionId || !tsDateCol || !tsValueCol) return;
      // Ferme la modale et affiche un placeholder animé dans « Éléments générés ».
      setIsTrainingModalOpen(false);
      setModalTraining(true);
      try {
        const apiUrl = API_URL;
        const model = typeof window !== "undefined" ? localStorage.getItem("selected_model") || undefined : undefined;
        const res = await fetch(`${apiUrl}/api/models/train-timeseries`, {
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
        // Le modèle est persisté : on recharge la liste → il apparaît, cliquable.
        await refetchModels();
      } catch (err) {
        alert(err instanceof Error ? err.message : "Erreur lors de l'entraînement.");
      } finally {
        setModalTraining(false);
      }
      return;
    }

    // ── Modèle prédictif : tournoi supervisé réel ──
    if (trainingType === "predictif") {
      if (!sessionId || !supTarget) return;
      setIsTrainingModalOpen(false);
      setModalTraining(true);
      try {
        const apiUrl = API_URL;
        const model = typeof window !== "undefined" ? localStorage.getItem("selected_model") || undefined : undefined;
        const res = await fetch(`${apiUrl}/api/models/train-supervised`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: sessionId, target: supTarget, model }),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok) throw new Error(data?.detail || "Échec de l'entraînement.");
        // Le modèle est persisté : on recharge la liste → il apparaît, cliquable.
        await refetchModels();
      } catch (err) {
        alert(err instanceof Error ? err.message : "Erreur lors de l'entraînement.");
      } finally {
        setModalTraining(false);
      }
      return;
    }
  };

  return (
    <>
      <div className="studio-panel" style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        background: "var(--bg-panel)",
        borderRadius: "12px",
        border: "1px solid var(--border-color)",
        borderBottom: "none",
        overflow: "hidden",
      }}>
        <div style={{
          padding: "20px 20px 14px",
          fontFamily: "var(--font-google-sans), sans-serif",
          fontSize: "16px",
          fontWeight: 500,
          color: "var(--text-main)",
          borderBottom: "1px solid var(--border-color)",
        }}>
          Studio
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", padding: "16px", flexShrink: 0 }}>

          {/* Dashboard Interactif */}
          <GlareHover
            onClick={() => { if (sessionId) window.open(`/dashboard/${sessionId}`, "_blank"); }}
            background="var(--bubble-ai)"
            borderColor="var(--border-color)"
            borderRadius="14px"
            glareOpacity={0.3}
            style={{
              padding: "16px 14px",
              cursor: sessionId ? "pointer" : "not-allowed",
              minHeight: "90px",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
              opacity: sessionId ? 1 : 0.5,
            }}
            onMouseEnter={(e) => { if (sessionId) (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-user)'); }}
            onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-ai)')}
          >
            <LayoutDashboard size={23} strokeWidth={1.7} />
            <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)", marginTop: "10px", lineHeight: 1.3 }}>
              Dashboard interactif
            </div>
          </GlareHover>

          <GlareHover
            onClick={() => openReportModal()}
            background="var(--bubble-ai)"
            borderColor="var(--border-color)"
            borderRadius="14px"
            glareOpacity={0.3}
            style={{
              padding: "16px 14px",
              cursor: "pointer",
              minHeight: "90px",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
            onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-user)')}
            onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-ai)')}
          >
            <FileText size={22} strokeWidth={1.7} />
            <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)", marginTop: "10px", lineHeight: 1.3 }}>
              Générer un rapport
            </div>
          </GlareHover>

          <GlareHover
            onClick={() => openReportModal("powerpoint")}
            background="var(--bubble-ai)"
            borderColor="var(--border-color)"
            borderRadius="14px"
            glareOpacity={0.3}
            style={{
              padding: "16px 14px",
              cursor: "pointer",
              minHeight: "90px",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
            }}
            onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-user)')}
            onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-ai)')}
          >
            <Presentation size={22} strokeWidth={1.7} />
            <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)", marginTop: "10px", lineHeight: 1.3 }}>
              Générer un PowerPoint
            </div>
          </GlareHover>

          {/* Cartes bientôt */}
          {STUDIO_ITEMS_SOON.map((item, i) => (
            <GlareHover key={i}
              background="var(--bubble-ai)"
              borderColor="var(--border-color)"
              borderRadius="14px"
              glareOpacity={0.15}
              style={{
                padding: "16px 14px",
                cursor: "not-allowed",
                minHeight: "90px",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
              }}
            >
              <span style={{
                position: "absolute", top: "10px", right: "10px",
                fontSize: "9px", background: "var(--border-color)",
                border: "1px solid var(--border-color)", color: "var(--text-muted)",
                padding: "2px 7px", borderRadius: "4px", letterSpacing: ".04em",
                zIndex: 20
              }}>BIENTÔT</span>
              <span style={{ fontSize: "20px" }}>{item.icon}</span>
              <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-muted)", marginTop: "10px", lineHeight: 1.3 }}>
                {item.label}
              </div>
            </GlareHover>
          ))}

          <GlareHover
            onClick={() => { if (sessionId && anyModelPossible) openTrainingModal(); }}
            background="var(--bubble-ai)"
            borderColor="var(--border-color)"
            borderRadius="14px"
            glareOpacity={sessionId && anyModelPossible ? 0.3 : 0}
            style={{
              gridColumn: "1 / -1",
              padding: "15px 16px",
              cursor: sessionId && anyModelPossible ? "pointer" : "not-allowed",
              minHeight: "72px",
              display: "flex",
              alignItems: "center",
              gap: "12px",
              opacity: sessionId && anyModelPossible ? 1 : 0.5,
            }}
            onMouseEnter={(e) => { if (sessionId && anyModelPossible) (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-user)'); }}
            onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-ai)')}
          >
            <span style={{ display: "grid", placeItems: "center", width: "38px", height: "38px", borderRadius: "12px", color: "var(--accent-color)", background: "var(--accent-soft)" }}><BrainCircuit size={21} strokeWidth={1.7} /></span>
            <div>
              <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-main)" }}>Entraîner un modèle</div>
              <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                {!sessionId
                  ? "Chargez d'abord un jeu de données."
                  : anyModelPossible
                    ? "Créer et suivre vos modèles prédictifs"
                    : "Aucun modèle compatible avec ce jeu de données."}
              </div>
            </div>
          </GlareHover>
        </div>

        <div style={{ borderTop: "1px solid var(--border-color)", display: "flex", flexDirection: "column", flex: 1, minHeight: 0, background: "color-mix(in srgb, var(--bg-chat) 42%, transparent)" }}>
          <div style={{ padding: "16px 20px 12px", display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
            <div>
              <div style={{ fontSize: "13px", fontWeight: 650, color: "var(--text-main)" }}>Éléments générés</div>
              <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>Rapports, modèles et résultats de cette session</div>
            </div>
            {sessionId && <span style={{ width: "7px", height: "7px", borderRadius: "999px", background: "#75d79b", boxShadow: "0 0 0 4px rgba(117,215,155,.1)" }} />}
          </div>

          <div style={{ padding: "0 16px 18px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "9px" }}>
            <style>{`@keyframes studio-pulse { 0%,100% { opacity: 1 } 50% { opacity: .55 } } @keyframes studio-spin { to { transform: rotate(360deg) } }`}</style>

            {/* Placeholders animés : un modèle est en cours de génération. */}
            {(chatModelPending || modalTraining) && (
              <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "12px", borderRadius: "12px", border: "1px solid var(--accent-color)", background: "var(--accent-soft)", animation: "studio-pulse 1.4s ease-in-out infinite" }}>
                <Loader2 size={16} style={{ color: "var(--accent-color)", animation: "studio-spin 1s linear infinite" }} />
                <span style={{ flex: 1 }}>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-main)" }}>Génération du modèle en cours…</div>
                  <div style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "3px" }}>Cela peut prendre jusqu’à ~2 minutes</div>
                </span>
              </div>
            )}

            {/* Modèles réels de la session (chat + modale) — cliquables. */}
            {trainedModels.map((m) => (
              <button
                key={m.id}
                onClick={() => openModelDashboard(m.id)}
                style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", padding: "12px", borderRadius: "12px", border: "1px solid var(--border-muted)", color: "var(--text-main)", background: "var(--bubble-ai)", cursor: "pointer", textAlign: "left" }}
              >
                <span style={{ display: "grid", placeItems: "center", width: "30px", height: "30px", borderRadius: "8px", flexShrink: 0, color: "var(--accent-color)", background: "var(--accent-soft)" }}>
                  {m.type === "timeseries" ? <LineChart size={16} strokeWidth={1.8} /> : <BrainCircuit size={16} strokeWidth={1.8} />}
                </span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "12px", fontWeight: 600, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{m.name}</div>
                  <div style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "3px" }}>
                    {m.type === "timeseries" ? "Modèle • Série temporelle" : "Modèle"}
                  </div>
                </span>
                <span style={{ fontSize: "10px", color: "var(--accent-color)", fontWeight: 700, flexShrink: 0 }}>Dashboard</span>
              </button>
            ))}

            {/* Rapports générés (client). */}
            {generatedItems.filter((it) => it.kind === "report").map((item) => (
              <button
                key={item.id}
                onClick={() => openGeneratedItem(item)}
                style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", padding: "12px", borderRadius: "12px", border: "1px solid var(--border-muted)", color: "var(--text-main)", background: "var(--bubble-ai)", cursor: "pointer", textAlign: "left" }}
              >
                <span style={{ flex: 1 }}>
                  <div style={{ fontSize: "12px", fontWeight: 600 }}>{item.title}</div>
                  <div style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "3px" }}>
                    {`Rapport • ${FORMATS_RAPPORT.find((f) => f.id === item.format)?.label || "Fichier"}`}
                  </div>
                </span>
                <span style={{ fontSize: "10px", color: "var(--accent-color)", fontWeight: 700 }}>Ouvrir</span>
              </button>
            ))}

            {/* État vide. */}
            {!chatModelPending && !modalTraining && trainedModels.length === 0 && generatedItems.filter((it) => it.kind === "report").length === 0 && !generatedContent && (
              <div style={{ fontSize: "12px", color: "var(--text-dim)", padding: "8px 2px" }}>
                Aucun élément généré pour l’instant. Générez un rapport ou entraînez un modèle.
              </div>
            )}

            {generatedContent && (
              <div style={{ padding: "14px", borderRadius: "12px", border: "1px solid var(--border-muted)", background: "var(--bubble-ai)" }}>
                <div style={{
                  fontSize: "12px",
                  fontWeight: 600,
                  color: "var(--text-main)",
                  marginBottom: "8px",
                }}>
                  Dernier résultat
                </div>
                <div style={{
                  fontSize: "12px",
                  lineHeight: 1.5,
                  color: "var(--text-muted)",
                  whiteSpace: "pre-wrap",
                  maxHeight: "120px",
                  overflowY: "auto",
                }}>
                  {generatedContent}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <Modal isOpen={isReportModalOpen} onClose={() => setIsReportModalOpen(false)} title="Générer un rapport" maxWidth="560px">
        <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
          <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "13px" }}>
            Vous pouvez laisser la description vide et générer directement le rapport.
          </p>
          <div style={{ position: "relative" }}>
            <textarea
              value={reportKeyPoints}
              onChange={(event) => setReportKeyPoints(event.target.value)}
              style={{ minHeight: "110px", resize: "vertical", borderRadius: "12px", border: "1px solid var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)", padding: "12px", fontSize: "13px", width: "100%", boxSizing: "border-box" }}
            />
            {!reportKeyPoints.trim() && (
              <div style={{ position: "absolute", inset: "12px 12px auto 12px", pointerEvents: "none" }}>
                <AnimatePresence mode="wait">
                  <motion.div
                    key={placeholderIndex}
                    initial={{ y: 6, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    exit={{ y: -10, opacity: 0 }}
                    transition={{ duration: 0.22, ease: "easeOut" }}
                    style={{ color: "var(--text-muted)", fontSize: "13px" }}
                  >
                    {REPORT_PLACEHOLDERS[placeholderIndex]}
                  </motion.div>
                </AnimatePresence>
              </div>
            )}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-main)" }}>Choisir le format</div>
            <div style={{ display: "flex", gap: "10px" }}>
              {FORMATS_RAPPORT.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => setReportFormat(f.id)}
                  style={{ flex: 1, padding: "10px 12px", borderRadius: "10px", border: reportFormat === f.id ? "1px solid var(--accent-color)" : "1px solid var(--border-muted)", background: reportFormat === f.id ? "var(--accent-soft)" : "var(--bubble-ai)", color: "var(--text-main)", fontWeight: 600 }}
                >
                  {f.label}
                </button>
              ))}
            </div>
          </div>
          <button
            type="button"
            onClick={handleReportSubmit}
            disabled={!sessionId || !reportFormat || isGeneratingReport}
            style={{ padding: "11px 12px", borderRadius: "10px", border: "none", background: "var(--accent-color)", color: "white", fontWeight: 700, cursor: (!sessionId || !reportFormat || isGeneratingReport) ? "not-allowed" : "pointer", opacity: (!sessionId || !reportFormat || isGeneratingReport) ? 0.6 : 1 }}
          >
            {isGeneratingReport ? "Génération en cours..." : "Générer"}
          </button>
        </div>
      </Modal>

      <Modal isOpen={isTrainingModalOpen} onClose={() => setIsTrainingModalOpen(false)} title="Entraîner un modèle" maxWidth="560px">
        <div style={{ display: "flex", flexDirection: "column", gap: "14px" }}>
          <p style={{ margin: 0, color: "var(--text-muted)", fontSize: "13px" }}>
            Choisissez un type de modèle et donnez-lui un nom avant de lancer l’entraînement.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            <label style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-main)" }}>Type de modèle</label>
            <div style={{ display: "flex", gap: "10px", flexWrap: "wrap" }}>
              {(
                [
                  { id: "predictif" as const, label: "Modèle prédictif", possible: supCibles.length > 0 },
                  { id: "timeseries" as const, label: "Séries temporelles", possible: tsCandidates.feasible },
                ]
              ).map((opt) => (
                <button
                  key={opt.id}
                  type="button"
                  disabled={!opt.possible}
                  onClick={() => choisirTypeEntrainement(opt.id)}
                  title={opt.possible ? undefined : "Ce jeu de données n'a pas les colonnes nécessaires pour ce type de modèle."}
                  style={{
                    flex: "1 1 45%",
                    padding: "10px 12px",
                    borderRadius: "10px",
                    border: trainingType === opt.id ? "1px solid var(--accent-color)" : "1px solid var(--border-muted)",
                    background: trainingType === opt.id ? "var(--accent-soft)" : "var(--bubble-ai)",
                    color: "var(--text-main)",
                    fontWeight: 600,
                    cursor: opt.possible ? "pointer" : "not-allowed",
                    opacity: opt.possible ? 1 : 0.4,
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            {!anyModelPossible && (
              <small style={{ color: "var(--text-muted)", fontSize: "11px" }}>
                Aucun type de modèle n’est compatible avec ce jeu de données (il faut par exemple au moins 20 lignes et plusieurs colonnes numériques ou catégorielles adaptées).
              </small>
            )}
          </div>

          {/* Proposition du LLM : une présélection argumentée, que les sélecteurs
              ci-dessous laissent librement modifier. */}
          {trainingType && (propositionEnCours || proposition?.motif) && (
            <div style={{ padding: "10px 12px", borderRadius: "10px", background: "var(--bubble-ai)", border: "1px dashed var(--border-muted)" }}>
              {propositionEnCours ? (
                <div style={{ fontSize: "11px", color: "var(--text-muted)", display: "flex", alignItems: "center", gap: "7px" }}>
                  <Loader2 size={13} className="animate-spin" />
                  Analyse des colonnes par le modèle…
                </div>
              ) : (
                <>
                  <div style={{ fontSize: "11px", fontWeight: 600, color: "var(--text-main)" }}>
                    Proposition du modèle
                  </div>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "3px", lineHeight: 1.5 }}>
                    {proposition?.motif} Vous pouvez la modifier ci-dessous.
                  </div>
                </>
              )}
            </div>
          )}

          {trainingType === "timeseries" ? (
            /* Configuration série temporelle : colonnes + horizon + moteur */
            <>
              <div style={{ display: "flex", gap: "10px" }}>
                <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "6px" }}>
                  <label style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-main)" }}>Colonne date</label>
                  <select value={tsDateCol} onChange={(e) => setTsDateCol(e.target.value)} style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }}>
                    {tsCandidates.date_columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "6px" }}>
                  <label style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-main)" }}>Colonne valeur</label>
                  <select value={tsValueCol} onChange={(e) => setTsValueCol(e.target.value)} style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }}>
                    {tsCandidates.value_columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>
              <div style={{ display: "flex", gap: "10px" }}>
                <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: "6px" }}>
                  <label style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-main)" }}>Horizon (périodes)</label>
                  <input type="number" min={1} value={tsHorizon} onChange={(e) => setTsHorizon(e.target.value)} style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }} />
                </div>
              </div>

              {/* Moteur : TimeCopilot, sauf si le modèle LLM sélectionné ne gère
                  pas le tool-use — le backend l'a dit AVANT le lancement. */}
              {engineInfo && engineInfo.engine === "timecopilot" ? (
                <small style={{ color: "var(--text-muted)", fontSize: "11px" }}>
                  Moteur <strong>TimeCopilot</strong> : il analyse la série, met plusieurs modèles en
                  concurrence, retient le meilleur et argumente son choix. Comptez quelques minutes.
                </small>
              ) : engineInfo ? (
                <div style={{ padding: "12px", borderRadius: "10px", background: "var(--bubble-ai)", border: "1px solid var(--warning-border, #b06000)" }}>
                  <div style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-main)", marginBottom: "6px" }}>
                    TimeCopilot indisponible pour ce modèle
                  </div>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>
                    {engineInfo.avertissement}
                  </div>
                  {engineInfo.message_repli && (
                    <div style={{ fontSize: "11px", color: "var(--text-muted)", lineHeight: 1.5, marginTop: "8px" }}>
                      {engineInfo.message_repli}
                    </div>
                  )}
                  <label style={{ display: "flex", alignItems: "flex-start", gap: "8px", marginTop: "10px", fontSize: "11px", color: "var(--text-main)", cursor: "pointer" }}>
                    <input
                      type="checkbox"
                      checked={repliAccepte}
                      onChange={(e) => setRepliAccepte(e.target.checked)}
                      style={{ marginTop: "2px" }}
                    />
                    <span>Continuer quand même avec AutoForecast, en acceptant des résultats
                      possiblement moins bons et non argumentés.</span>
                  </label>
                </div>
              ) : null}
            </>
          ) : trainingType === "predictif" ? (
            /* On ne choisit QUE la variable à prédire : la famille en découle et
               tous les modèles de cette famille sont mis en concurrence. */
            <>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-main)" }}>Variable à prédire</label>
                <select
                  value={supTarget}
                  onChange={(e) => setSupTarget(e.target.value)}
                  style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }}
                >
                  <option value="">— Choisir une colonne —</option>
                  {supCibles.map((c) => (
                    <option key={c.colonne} value={c.colonne}>{c.colonne}</option>
                  ))}
                </select>
              </div>
              {cibleChoisie && (
                <div style={{ padding: "10px 12px", borderRadius: "10px", background: "var(--bubble-ai)", border: "1px solid var(--border-muted)" }}>
                  <div style={{ fontSize: "12px", color: "var(--text-main)", fontWeight: 600 }}>
                    {FAMILLES_LABEL[cibleChoisie.famille] ?? cibleChoisie.famille}
                  </div>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "3px" }}>
                    {cibleChoisie.famille === "regression"
                      ? `Valeur continue (${cibleChoisie.n_modalites} valeurs distinctes).`
                      : `${cibleChoisie.n_modalites} classes` +
                        (cibleChoisie.ratio_minoritaire != null
                          ? ` — la plus rare représente ${(cibleChoisie.ratio_minoritaire * 100).toFixed(1)} %.`
                          : ".")}
                  </div>
                </div>
              )}
              <small style={{ color: "var(--text-muted)", fontSize: "11px" }}>
                Vous ne choisissez pas le modèle : trois modèles de la famille sont mis en
                concurrence et le meilleur est retenu. Un modèle n’est validé que si ses
                hypothèses statistiques ET ses performances tiennent. Budget 10 minutes,
                interrompu dès qu’un modèle satisfait toutes les normes.
              </small>
            </>
          ) : null}
          {(() => {
            // Le repli AutoForecast doit être explicitement accepté : l'utilisateur
            // avait demandé TimeCopilot, on ne lui substitue pas un autre moteur
            // sans son accord.
            const repliRequis = trainingType === "timeseries"
              && engineInfo != null && engineInfo.engine !== "timecopilot";
            const bloque = !trainingType || modalTraining
              || (trainingType === "timeseries" ? (!tsDateCol || !tsValueCol) : !supTarget)
              || (repliRequis && !repliAccepte);
            return (
              <button
                type="button"
                onClick={handleTrainingSubmit}
                disabled={bloque}
                style={{ padding: "11px 12px", borderRadius: "10px", border: "none", background: "var(--accent-color)", color: "white", fontWeight: 700, cursor: bloque ? "not-allowed" : "pointer", opacity: bloque ? 0.6 : 1 }}
              >
                {modalTraining ? "Entraînement en cours…"
                  : repliRequis ? "Entraîner avec AutoForecast" : "Entraîner"}
              </button>
            );
          })()}
        </div>
      </Modal>
    </>
  );
}
