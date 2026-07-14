"use client";
import { useRef, useState } from "react";
import SplitText from "./SplitText";
import { UploadIcon } from "./UploadIcon";

interface Source {
  name: string;
  type: "tabular" | "document";
  meta: string;
}

interface Props {
  sources: Source[];
  onUpload: (data: any) => void;
  onRemove: (index: number) => void;
  hideHeader?: boolean;
  style?: React.CSSProperties;
  selectedModel?: string;
}

export default function SourcesPanel({ sources, onUpload, onRemove, hideHeader = false, style, selectedModel }: Props) {
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

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;

    const formData = new FormData();
    formData.append("file", f);
    if (selectedModel) {
      formData.append("model", selectedModel);
    }

    setLoadingState({
      isLoading: true,
      fileName: f.name,
      step: 1,
      message: "Lecture et détection du format du fichier...",
    });

    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/upload`, {
        method: "POST",
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
            return;
          }
        }
      }
    } catch (err: any) {
      console.error(err);
      alert("Erreur lors du chargement. Vérifiez que le backend est démarré.");
      setLoadingState(prev => ({ ...prev, isLoading: false }));
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  return (
    <div style={{
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
          fontFamily: "'Google Sans',sans-serif",
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
        <span style={{ color: "var(--text-muted)", display: "flex", alignItems: "center" }}>
          <svg data-name="i-search" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" width="18" height="18">
            <path d="M21.25 21.25L16.8702 16.8017M19.2504 10.9994C19.2504 15.5557 15.5567 19.2494 11.0004 19.2494C6.44402 19.2494 2.75037 15.5557 2.75037 10.9994C2.75037 6.44304 6.44402 2.74939 11.0004 2.74939C15.5567 2.74939 19.2504 6.44304 19.2504 10.9994Z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </span>
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

          {/* Mini barre de progression */}
          <div style={{ width: "100%", background: "var(--border-color)", height: "4px", borderRadius: "2px", overflow: "hidden" }}>
            <div style={{
              height: "100%",
              background: "var(--accent-color)",
              width: `${loadingState.step === 1 ? 25 : loadingState.step === 2 ? 50 : loadingState.step === 3 ? 75 : 95}%`,
              borderRadius: "2px",
              transition: "width 0.5s cubic-bezier(0.4, 0, 0.2, 1)",
            }} />
          </div>
        </div>
      ) : (
        <button
          onClick={() => fileInputRef.current?.click()}
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
        accept=".csv,.xlsx,.xls,.pdf,.docx"
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
            Ajoutez un fichier CSV, Excel ou PDF.
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
              {src.type === "tabular" ? "📗" : "📕"}
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

            <span style={{ color: "var(--accent-color)", fontSize: "16px", flexShrink: 0 }}>✓</span>

            <button
              onClick={() => onRemove(i)}
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
              ×
            </button>
          </div>
        ))}
      </div>


    </div>
  );
}