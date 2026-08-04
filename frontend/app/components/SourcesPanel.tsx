"use client";
import { useEffect, useRef, useState } from "react";
import SplitText from "./SplitText";
import { UploadIcon } from "./UploadIcon";
import Modal from "./Modal";
import { Progress } from "./Progress";
import { API_URL } from "@/lib/api";
import { Check, FileText, Search, Table2, X } from "lucide-react";

interface Source {
  name: string;
  type: "tabular" | "document";
  meta: string;
}

interface UploadData {
  session_id: string;
  filename?: string;
  profile?: {
    filename?: string;
  };
  type: string;
  interpretation?: string;
  summary?: string;
  /** Renseigné quand le fichier a été rattaché à une session déjà ouverte. */
  dataset_id?: string;
}

interface Props {
  sources: Source[];
  onUpload: (data: UploadData) => void;
  onRemove: (index: number) => void;
  hideHeader?: boolean;
  style?: React.CSSProperties;
  selectedModel?: string;
  registerUploadHandler?: (handler: (() => void) | null) => void;
  /** Session ouverte : les imports suivants s'y rattachent au lieu d'en créer une. */
  sessionId?: string | null;
}

export default function SourcesPanel({ sources, onUpload, onRemove, hideHeader = false, style, selectedModel, registerUploadHandler, sessionId }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploadHovered, setIsUploadHovered] = useState(false);
  const [loadingState, setLoadingState] = useState<{
    isLoading: boolean;
    fileName: string;
    step: number;
    message: string;
  }>({
    isLoading: false,
    fileName: "",
    step: 1,
    message: "",
  });

  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  // Fusion proposée quand un fichier ajouté a exactement les mêmes colonnes
  // qu'un jeu déjà présent — le cas du tableau livré en deux parties. Jamais
  // automatique : concaténer des données est une décision de l'utilisateur.
  const [fusionProposee, setFusionProposee] = useState<{
    sessionId: string;
    nouveauId: string;
    nouveauNom: string;
    nouveauLignes?: number;
    candidatId: string;
    candidatNom: string;
    candidatLignes?: number;
  } | null>(null);
  const [fusionEnCours, setFusionEnCours] = useState(false);
  const [fusionErreur, setFusionErreur] = useState("");

  type JeuDeDonnees = { id: string; name: string; rows?: number };

  const proposerFusion = async (sid: string, nouveauId: string) => {
    try {
      const res = await fetch(`${API_URL}/api/sessions/${sid}/datasets`);
      if (!res.ok) return;
      const data = await res.json();
      const candidats: string[] = data.fusionnables?.[nouveauId] ?? [];
      if (candidats.length === 0) return;

      const jeux: JeuDeDonnees[] = data.datasets ?? [];
      const nouveau = jeux.find((j) => j.id === nouveauId);
      const candidat = jeux.find((j) => j.id === candidats[0]);
      if (!nouveau || !candidat) return;

      setFusionErreur("");
      setFusionProposee({
        sessionId: sid,
        nouveauId, nouveauNom: nouveau.name, nouveauLignes: nouveau.rows,
        candidatId: candidat.id, candidatNom: candidat.name, candidatLignes: candidat.rows,
      });
    } catch {
      // La fusion n'est qu'une commodité : son échec ne doit pas gêner l'import.
    }
  };

  const confirmerFusion = async () => {
    if (!fusionProposee) return;
    setFusionEnCours(true);
    setFusionErreur("");
    try {
      const res = await fetch(
        `${API_URL}/api/sessions/${fusionProposee.sessionId}/datasets/merge`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            base_id: fusionProposee.candidatId,
            ajout_id: fusionProposee.nouveauId,
          }),
        },
      );
      const data = await res.json().catch(() => null);
      if (!res.ok) throw new Error(data?.detail || "La fusion a échoué.");
      setFusionProposee(null);
      onUpload({
        session_id: fusionProposee.sessionId,
        type: "dataset_added",
        filename: data?.filename,
      });
    } catch (err) {
      setFusionErreur(err instanceof Error ? err.message : "La fusion a échoué.");
    } finally {
      setFusionEnCours(false);
    }
  };

  useEffect(() => {
    registerUploadHandler?.(() => setIsUploadModalOpen(true));
    return () => {
      registerUploadHandler?.(null);
    };
  }, [registerUploadHandler]);

  const processFile = async (f: File) => {

    const formData = new FormData();
    formData.append("file", f);
    // Le backend applique son modèle local par défaut. On n'envoie donc jamais
    // une valeur vide ou périmée sauvegardée dans le navigateur.
    const model = selectedModel?.trim();
    if (model) formData.append("model", model);
    formData.append("index_doc", "true");
    // Une session déjà ouverte reçoit le fichier comme source SUPPLÉMENTAIRE.
    // Sans cet identifiant, le backend créait une nouvelle session à chaque
    // import : impossible de charger un jeu de données et ses métadonnées, ou
    // un tableau livré en deux parties, dans un même contexte.
    if (sessionId) formData.append("session_id", sessionId);

    setLoadingState({
      isLoading: true,
      fileName: f.name,
      step: 1,
      message: "Lecture et détection du format du fichier...",
    });

    try {
      const apiUrl = API_URL;
      const res = await fetch(`${apiUrl}/api/upload`, {
        method: "POST",
        headers: {
          "accept": "application/json"
        },
        body: formData,
      });

      if (!res.body) {
        throw new Error("Pas de flux de réponse reçu du serveur.");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.trim()) continue;

          let payload;
          try {
            payload = JSON.parse(line);
          } catch (err) {
            console.error("Erreur de parsing JSON sur la ligne :", line, err);
            continue;
          }

          if (payload.status === "processing") {
            setLoadingState(prev => ({
              ...prev,
              step: payload.step,
              message: payload.message,
            }));
          } else if (payload.status === "error") {
            alert(payload.message || "Une erreur est survenue lors du traitement.");
            setLoadingState(prev => ({ ...prev, isLoading: false }));
            return;
          } else if (payload.status === "clarification_needed") {
            alert(payload.message);
            setLoadingState(prev => ({ ...prev, isLoading: false }));
            return;
          } else if (payload.status === "completed") {
            const finalData = payload.data;
            finalData.filename = f.name;
            onUpload(finalData);
            setLoadingState(prev => ({ ...prev, isLoading: false }));
            // Fichier ajouté à une session : peut-être la suite d'un jeu déjà
            // présent. On le vérifie après coup pour ne pas retarder l'import.
            if (finalData.type === "dataset_added" && finalData.session_id && finalData.dataset_id) {
              void proposerFusion(finalData.session_id, finalData.dataset_id);
            }
            return;
          }
        }
      }
    } catch (err) {
      console.error(err);
      alert("Erreur lors du chargement. Vérifiez que le backend est démarré.");
      setLoadingState(prev => ({ ...prev, isLoading: false }));
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setIsUploadModalOpen(false);
    await processFile(f);
  };

  return (
    <div className="sources-panel" style={{
      height: "100%",
      display: "flex",
      flexDirection: "column",
      background: "transparent",
      overflow: "hidden",
      ...style
    }}>
      {/* Titre */}
      {!hideHeader && (
        <div style={{
          padding: "16px 20px 14px",
          fontFamily: "var(--font-google-sans), sans-serif",
          fontSize: "16px",
          fontWeight: 500,
          color: "var(--text-main)",
        }}>
          Sources
        </div>
      )}

      {/* Recherche */}
      <div style={{
        margin: "12px 16px 12px",
        display: "flex",
        alignItems: "center",
        gap: "10px",
        background: "var(--bubble-ai)",
        border: "1px solid var(--border-muted)",
        borderRadius: "24px",
        padding: "8px 16px",
      }}>
        <Search size={17} strokeWidth={1.8} color="var(--text-muted)" />
        <input
          placeholder="Rechercher une source"
          style={{
            flex: 1,
            background: "transparent",
            border: "none",
            color: "var(--text-main)",
            fontSize: "14px",
            outline: "none",
          }}
        />
      </div>

      {/* Tout sélectionner */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: "10px",
        padding: "8px 20px 10px",
        borderBottom: "1px solid var(--border-muted)",
      }}>
        <input
          type="checkbox"
          defaultChecked
          style={{ accentColor: "var(--accent-color)", width: "15px", height: "15px" }}
        />
        <span style={{ fontSize: "13px", color: "var(--text-muted)" }}>
          Tout sélectionner
        </span>
      </div>

      {/* Bouton ajouter ou Sablier de Chargement en cours */}
      {loadingState.isLoading ? (
        <div style={{
          margin: "12px 16px",
          padding: "16px",
          background: "var(--bubble-user)",
          border: "1px dashed var(--accent-color)",
          borderRadius: "12px",
          display: "flex",
          flexDirection: "column",
          gap: "12px",
          boxShadow: "0 4px 12px rgba(0, 0, 0, 0.04)",
        }}>
          {/* Header de chargement avec le sablier */}
          <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
            <div style={{ color: "var(--accent-color)", flexShrink: 0, display: "flex", alignItems: "center" }}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="animate-hourglass">
                <path d="M5 2h14" />
                <path d="M5 22h14" />
                <path d="M19 2v4c0 3-2 5-5 5v2c3 0 5 2 5 5v4" />
                <path d="M5 2v4c0 3 2 5 5 5v2c-3 0-5 2-5 5v4" />
                <path d="M12 11h.01" />
              </svg>
            </div>
            <div style={{
              fontSize: "12px",
              fontWeight: 600,
              color: "var(--text-main)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              flex: 1
            }}>
              {loadingState.fileName}
            </div>
            <div style={{
              fontSize: "11px",
              fontWeight: 700,
              color: "var(--accent-color)",
              background: "var(--border-color)",
              padding: "2px 6px",
              borderRadius: "10px",
            }}>
              {loadingState.step === 1 && "25%"}
              {loadingState.step === 2 && "50%"}
              {loadingState.step === 3 && "75%"}
              {loadingState.step === 4 && "95%"}
            </div>
          </div>

          {/* Etape avec animation SplitText */}
          <div style={{
            fontSize: "13px",
            color: "var(--text-main)",
            fontWeight: 500,
            minHeight: "36px",
            display: "flex",
            alignItems: "center",
          }}>
            <SplitText
              text={loadingState.message}
              className="text-left font-medium"
              delay={35}
              duration={0.5}
              ease="power2.out"
              splitType="chars"
              from={{ opacity: 0, y: 15 }}
              to={{ opacity: 1, y: 0 }}
              threshold={0.1}
              textAlign="left"
            />
          </div>

          {/* Mini barre de progression Radix UI */}
          <Progress
            value={loadingState.step === 1 ? 25 : loadingState.step === 2 ? 50 : loadingState.step === 3 ? 75 : 95}
            className="h-1.5"
          />
        </div>
      ) : (
        <button
          onClick={() => setIsUploadModalOpen(true)}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "8px",
            margin: "12px 16px",
            padding: "10px",
            border: "1.5px dashed var(--border-color)",
            borderRadius: "12px",
            color: "var(--text-muted)",
            fontSize: "13px",
            background: "transparent",
            cursor: "pointer",
            width: "calc(100% - 32px)",
            transition: "all .15s",
          }}
          onMouseEnter={e => {
            setIsUploadHovered(true);
            (e.currentTarget as HTMLElement).style.borderColor = "var(--accent-color)";
            (e.currentTarget as HTMLElement).style.color = "var(--accent-color)";
          }}
          onMouseLeave={e => {
            setIsUploadHovered(false);
            (e.currentTarget as HTMLElement).style.borderColor = "var(--border-color)";
            (e.currentTarget as HTMLElement).style.color = "var(--text-muted)";
          }}
        >
          <UploadIcon size={16} isHovered={isUploadHovered} /> Ajouter une source
        </button>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,.xlsx,.xls,.pdf,.docx,.md,.tex"
        style={{ display: "none" }}
        onChange={handleFile}
      />

      {/* Liste des sources */}
      <div style={{ flex: 1, overflowY: "auto", padding: "4px 0" }}>
        {sources.length === 0 && (
          <div style={{
            textAlign: "center",
            color: "var(--text-dim)",
            fontSize: "13px",
            padding: "40px 20px",
            lineHeight: 1.7,
          }}>
            Aucune source chargée.<br />
            Ajoutez un fichier CSV, Excel, PDF, DOCX, Markdown ou LaTeX.
          </div>
        )}

        {sources.map((src, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "12px",
              padding: "10px 20px",
              cursor: "pointer",
              transition: "background .15s",
            }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = "var(--bubble-ai)"}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "transparent"}
          >
            <div style={{
              width: "32px",
              height: "32px",
              borderRadius: "6px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "16px",
              flexShrink: 0,
              background: src.type === "tabular"
                ? "rgba(52,168,83,0.15)"
                : "rgba(234,67,53,0.15)",
            }}>
              {src.type === "tabular" ? <Table2 size={16} color="#72d39b" /> : <FileText size={16} color="#e59a9a" />}
            </div>

            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{
                fontSize: "13px",
                color: "var(--text-main)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}>
                {src.name}
              </div>
              <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>
                {src.meta}
              </div>
            </div>

            <Check size={16} strokeWidth={2} color="var(--accent-color)" style={{ flexShrink: 0 }} />

            <button
              onClick={() => onRemove(i)}
              // Nommé avec la source concernée : plusieurs de ces boutons
              // cohabitent dans la liste, un simple « Retirer » ne dirait pas
              // lequel on s'apprête à supprimer.
              aria-label={`Retirer la source « ${src.name} »`}
              title={`Retirer « ${src.name} »`}
              style={{
                color: "#555",
                fontSize: "20px",
                flexShrink: 0,
                lineHeight: 1,
                cursor: "pointer",
                background: "none",
                border: "none",
                transition: "color .15s",
              }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = "#ea4335"}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = "#555"}
            >
              <X size={17} strokeWidth={1.8} />
            </button>
          </div>
        ))}
      </div>

      {/* Modal d'Upload Drag & Drop */}
      <Modal isOpen={isUploadModalOpen} onClose={() => setIsUploadModalOpen(false)} title="Ajouter une source" maxWidth="500px">
        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setIsDragging(false);
            const f = e.dataTransfer.files?.[0];
            if (f) {
              setIsUploadModalOpen(false);
              processFile(f);
            }
          }}
          onClick={() => fileInputRef.current?.click()}
          style={{
            border: `2px dashed ${isDragging ? "var(--accent-color)" : "var(--border-muted)"}`,
            borderRadius: "16px",
            padding: "48px 24px",
            textAlign: "center",
            background: isDragging ? "var(--bubble-ai)" : "transparent",
            transition: "all 0.2s ease",
            cursor: "pointer",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: "16px"
          }}
        >
          <div style={{
            width: "64px",
            height: "64px",
            borderRadius: "50%",
            background: "var(--bubble-user)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--accent-color)",
            boxShadow: "0 4px 12px rgba(0, 0, 0, 0.05)"
          }}>
            <UploadIcon size={32} isHovered={isDragging} />
          </div>
          <div>
            <div style={{ fontSize: "16px", fontWeight: 600, color: "var(--text-main)", marginBottom: "6px" }}>
              Glissez et déposez votre fichier ici
            </div>
            <div style={{ fontSize: "14px", color: "var(--text-muted)" }}>
              ou <span style={{ color: "var(--accent-color)", fontWeight: 500 }}>cliquez pour parcourir</span>
            </div>
          </div>
          <div style={{ fontSize: "12px", color: "var(--text-dim)", marginTop: "4px" }}>
            Formats supportés : CSV, XLSX, XLS, PDF, DOCX, MD, TEX
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={fusionProposee !== null}
        onClose={() => { if (!fusionEnCours) setFusionProposee(null); }}
        title="Ce fichier est-il la suite d’un autre ?"
        maxWidth="480px"
      >
        {fusionProposee && (
          <div className="flex flex-col gap-4" style={{ color: "var(--text-main)" }}>
            <p style={{ fontSize: "14px", lineHeight: 1.6, color: "var(--text-muted)" }}>
              <strong style={{ color: "var(--text-main)" }}>{fusionProposee.nouveauNom}</strong>{" "}
              a exactement les mêmes colonnes que{" "}
              <strong style={{ color: "var(--text-main)" }}>{fusionProposee.candidatNom}</strong>.
              Vous pouvez les réunir en un seul jeu de données, ou les garder séparés.
            </p>
            <div style={{
              fontSize: "13px", lineHeight: 1.8, padding: "12px 14px",
              borderRadius: "10px", background: "var(--bubble-ai)",
              border: "1px solid var(--border-muted)",
            }}>
              <div>{fusionProposee.candidatNom} — {fusionProposee.candidatLignes ?? "?"} lignes</div>
              <div>{fusionProposee.nouveauNom} — {fusionProposee.nouveauLignes ?? "?"} lignes</div>
              {typeof fusionProposee.candidatLignes === "number"
                && typeof fusionProposee.nouveauLignes === "number" && (
                <div style={{ marginTop: "6px", fontWeight: 600 }}>
                  Une fois réunis : {fusionProposee.candidatLignes + fusionProposee.nouveauLignes} lignes
                </div>
              )}
            </div>
            <p style={{ fontSize: "12px", color: "var(--text-dim)" }}>
              Les deux fichiers d’origine sont conservés : le jeu réuni s’ajoute à côté.
            </p>
            {fusionErreur && (
              <p role="alert" style={{ fontSize: "13px", color: "var(--status-danger)" }}>{fusionErreur}</p>
            )}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={() => setFusionProposee(null)}
                disabled={fusionEnCours}
                className="dashboard-secondary-action"
              >
                Les garder séparés
              </button>
              <button
                type="button"
                onClick={confirmerFusion}
                disabled={fusionEnCours}
                className="dashboard-secondary-action"
                style={{ background: "var(--accent-color)", color: "var(--bg-app)", borderColor: "var(--accent-color)" }}
              >
                {fusionEnCours ? "Fusion en cours…" : "Réunir en un seul jeu"}
              </button>
            </div>
          </div>
        )}
      </Modal>

    </div>
  );
}
