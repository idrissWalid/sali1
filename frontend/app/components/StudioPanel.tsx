"use client";
import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { AudioLines, BrainCircuit, FileDown, FileText, FolderOpen, LayoutDashboard, PackageCheck } from "lucide-react";
import Modal from "./Modal";
import GlareHover from './GlareHover';

interface Props {
  sessionId: string | null;
  sessionType?: string;
  generatedContent?: string;
  openModels?: () => void;
}

const STUDIO_ITEMS_SOON = [
  { icon: (
    <span style={{ display: "inline-flex", alignItems: "center" }}>
      <AudioLines size={22} strokeWidth={1.8} />
    </span>
  ), label: "Résumé audio" },
  { icon: (
    <span style={{ display: "inline-flex", alignItems: "center" }}>
      <FolderOpen size={22} strokeWidth={1.8} />
    </span>
  ), label: "Fiches synthèse" },
];

type ReportFormat = "pdf" | "word" | null;
type TrainingType = "classification" | "regression" | "prediction" | null;

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

export default function StudioPanel({ sessionId, sessionType = "tabular", generatedContent, openModels }: Props) {
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);
  const [isTrainingModalOpen, setIsTrainingModalOpen] = useState(false);
  const [reportFormat, setReportFormat] = useState<ReportFormat>(null);
  const [reportKeyPoints, setReportKeyPoints] = useState("");
  const [trainingType, setTrainingType] = useState<TrainingType>(null);
  const [trainingName, setTrainingName] = useState("");
  const [isGeneratingReport, setIsGeneratingReport] = useState(false);
  const [isTrainingModel, setIsTrainingModel] = useState(false);
  const [placeholderIndex, setPlaceholderIndex] = useState(0);
  const [generatedItems, setGeneratedItems] = useState<GeneratedItem[]>([]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setPlaceholderIndex((prev) => (prev + 1) % REPORT_PLACEHOLDERS.length);
    }, 3000);

    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    setGeneratedItems([]);
  }, [sessionId]);

  const addGeneratedItem = (item: GeneratedItem) => {
    setGeneratedItems((prev) => [item, ...prev]);
  };

  const openGeneratedItem = (item: GeneratedItem) => {
    if (item.url) {
      window.open(item.url, "_blank", "noopener,noreferrer");
    }
  };

  const downloadReport = async (format: "pdf" | "word", keyPoints = "") => {
    if (!sessionId) {
      alert("Aucune session active. Chargez d'abord un fichier.");
      return;
    }
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const reportTitle = keyPoints.trim()
        ? `Rapport d'analyse de données — ${keyPoints.trim().slice(0, 80)}`
        : "Rapport d'analyse de données";
      const res = await fetch(`${apiUrl}/api/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          title: reportTitle,
          institution: "CITADEL — Ouagadougou, Burkina Faso",
          format,
        }),
      });
      if (!res.ok) throw new Error("Erreur serveur");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      addGeneratedItem({
        id: `${Date.now()}-${format}`,
        title: keyPoints.trim() ? `Rapport • ${keyPoints.trim().slice(0, 40)}` : `Rapport d'analyse (${format === "pdf" ? "PDF" : "Word"})`,
        kind: "report",
        format,
        url,
      });
      const a = document.createElement("a");
      a.href = url;
      a.download = format === "pdf" ? "rapport_analyse.pdf" : "rapport_analyse.docx";
      a.click();
      window.open(url, "_blank", "noopener,noreferrer");
    } catch {
      alert("Erreur lors de la génération du rapport.");
    }
  };

  const openReportModal = () => {
    setReportFormat(null);
    setReportKeyPoints("");
    setIsReportModalOpen(true);
  };

  const openTrainingModal = () => {
    setTrainingType(null);
    setTrainingName("");
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

  const handleTrainingSubmit = () => {
    if (!trainingType || !trainingName.trim()) return;
    setIsTrainingModel(true);
    try {
      addGeneratedItem({
        id: `model-${Date.now()}`,
        title: trainingName.trim(),
        kind: "model",
        format: null,
      });
      openModels?.();
      setIsTrainingModalOpen(false);
    } finally {
      setIsTrainingModel(false);
    }
  };

  return (
    <>
      <div style={{
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
          fontFamily: "'Google Sans',sans-serif",
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
            onClick={() => { if (sessionId && sessionType === "tabular") window.open(`/dashboard/${sessionId}`, "_blank"); }}
            background="var(--bubble-ai)"
            borderColor="var(--border-color)"
            borderRadius="14px"
            glareOpacity={0.3}
            style={{
              padding: "16px 14px",
              cursor: (sessionId && sessionType === "tabular") ? "pointer" : "not-allowed",
              minHeight: "90px",
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
              opacity: (sessionId && sessionType === "tabular") ? 1 : 0.4,
            }}
            onMouseEnter={(e) => { if (sessionId && sessionType === "tabular") (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-user)'); }}
            onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-ai)')}
          >
            <LayoutDashboard size={23} strokeWidth={1.7} />
            <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)", marginTop: "10px", lineHeight: 1.3 }}>
              Dashboard interactif
              {sessionType !== "tabular" && sessionId && (
                <div style={{ fontSize: "11px", color: "var(--text-dim)", marginTop: "3px" }}>CSV/Excel uniquement</div>
              )}
            </div>
          </GlareHover>

          <GlareHover
            onClick={openReportModal}
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
            onClick={openTrainingModal}
            background="var(--bubble-ai)"
            borderColor="var(--border-color)"
            borderRadius="14px"
            glareOpacity={0.3}
            style={{
              gridColumn: "1 / -1",
              padding: "15px 16px",
              cursor: "pointer",
              minHeight: "72px",
              display: "flex",
              alignItems: "center",
              gap: "12px",
            }}
            onMouseEnter={(e) => (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-user)')}
            onMouseLeave={(e) => (e.currentTarget as HTMLElement).style.setProperty('--gh-bg', 'var(--bubble-ai)')}
          >
            <span style={{ display: "grid", placeItems: "center", width: "38px", height: "38px", borderRadius: "12px", color: "var(--accent-color)", background: "var(--accent-soft)" }}><BrainCircuit size={21} strokeWidth={1.7} /></span>
            <div>
              <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text-main)" }}>Entraîner un modèle</div>
              <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>Créer et suivre vos modèles prédictifs</div>
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


            {generatedItems.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                {generatedItems.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => openGeneratedItem(item)}
                    style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "10px", padding: "12px", borderRadius: "12px", border: "1px solid var(--border-muted)", color: "var(--text-main)", background: "var(--bubble-ai)", cursor: "pointer", textAlign: "left" }}
                  >
                    <span style={{ flex: 1 }}>
                      <div style={{ fontSize: "12px", fontWeight: 600 }}>{item.title}</div>
                      <div style={{ fontSize: "10px", color: "var(--text-muted)", marginTop: "3px" }}>
                        {item.kind === "report" ? `Rapport • ${item.format?.toUpperCase() || "Fichier"}` : "Modèle"}
                      </div>
                    </span>
                    <span style={{ fontSize: "10px", color: "var(--accent-color)", fontWeight: 700 }}>Ouvrir</span>
                  </button>
                ))}
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
              <button
                type="button"
                onClick={() => setReportFormat("pdf")}
                style={{ flex: 1, padding: "10px 12px", borderRadius: "10px", border: reportFormat === "pdf" ? "1px solid var(--accent-color)" : "1px solid var(--border-muted)", background: reportFormat === "pdf" ? "var(--accent-soft)" : "var(--bubble-ai)", color: "var(--text-main)", fontWeight: 600 }}
              >
                PDF
              </button>
              <button
                type="button"
                onClick={() => setReportFormat("word")}
                style={{ flex: 1, padding: "10px 12px", borderRadius: "10px", border: reportFormat === "word" ? "1px solid var(--accent-color)" : "1px solid var(--border-muted)", background: reportFormat === "word" ? "var(--accent-soft)" : "var(--bubble-ai)", color: "var(--text-main)", fontWeight: 600 }}
              >
                Word
              </button>
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
            <select
              value={trainingType || ""}
              onChange={(event) => setTrainingType(event.target.value as TrainingType)}
              style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }}
            >
              <option value="">Sélectionner</option>
              <option value="classification">Classification</option>
              <option value="regression">Régression</option>
              <option value="prediction">Prédiction</option>
            </select>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
            <label style={{ fontSize: "12px", fontWeight: 600, color: "var(--text-main)" }}>Nom du modèle</label>
            <input
              value={trainingName}
              onChange={(event) => setTrainingName(event.target.value)}
              placeholder="Ex. modèle_vente_2026"
              style={{ padding: "10px 12px", borderRadius: "10px", border: "1px solid var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-main)" }}
            />
          </div>
          <button
            type="button"
            onClick={handleTrainingSubmit}
            disabled={!trainingType || !trainingName.trim() || isTrainingModel}
            style={{ padding: "11px 12px", borderRadius: "10px", border: "none", background: "var(--accent-color)", color: "white", fontWeight: 700, cursor: (!trainingType || !trainingName.trim() || isTrainingModel) ? "not-allowed" : "pointer", opacity: (!trainingType || !trainingName.trim() || isTrainingModel) ? 0.6 : 1 }}
          >
            {isTrainingModel ? "Ouverture..." : "Entraîner"}
          </button>
        </div>
      </Modal>
    </>
  );
}
