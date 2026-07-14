"use client";

interface Props {
  sessionId: string | null;
}

const STUDIO_ITEMS_SOON = [
  { icon: (
    <span style={{ display: "inline-flex", alignItems: "center" }}>
      <svg width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3"></path>
      </svg>
    </span>
  ), label: "Résumé audio" },
  { icon: (
    <span style={{ display: "inline-flex", alignItems: "center" }}>
      <svg width="24" height="24" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M3 17V7a2 2 0 0 1 2-2h6l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"></path>
      </svg>
    </span>
  ), label: "Fiches synthèse" },
];

export default function StudioPanel({ sessionId }: Props) {

  const downloadReport = async (format: "pdf" | "word") => {
    if (!sessionId) {
      alert("Aucune session active. Chargez d'abord un fichier.");
      return;
    }
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/report`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          title: "Rapport d'analyse de données",
          institution: "CITADEL — Ouagadougou, Burkina Faso",
          format,
        }),
      });
      if (!res.ok) throw new Error("Erreur serveur");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = format === "pdf" ? "rapport_analyse.pdf" : "rapport_analyse.docx";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("Erreur lors de la génération du rapport.");
    }
  };

  return (
    <div style={{
      height: "99%",
      marginTop: "5px",
      display: "flex",
      flexDirection: "column",
      background: "var(--bg-panel)",
      borderRadius: "12px",
      border: "1px solid var(--border-color)",
      borderBottom: "none",
      overflowY: "auto",
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

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px", padding: "16px" }}>

        {/* Rapport PDF — actif */}
        <div
          onClick={() => downloadReport("pdf")}
          style={{
            background: "var(--bubble-ai)",
            border: "1px solid var(--border-color)",
            borderRadius: "14px",
            padding: "16px 14px",
            cursor: sessionId ? "pointer" : "not-allowed",
            position: "relative",
            minHeight: "90px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            opacity: sessionId ? 1 : 0.5,
            transition: "background .15s",
          }}
          onMouseEnter={e => { if (sessionId) (e.currentTarget as HTMLElement).style.background = "var(--bubble-user)"; }}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "var(--bubble-ai)"}
        >
          <span style={{ display: "inline-flex", alignItems: "center" }}>
            <svg width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
              <polyline points="14 2 14 8 20 8" />
              <path d="M12 18v-6" />
              <path d="m9 15 3 3 3-3" />
            </svg>
          </span>
          <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)", marginTop: "10px", lineHeight: 1.3 }}>
            Rapport PDF
          </div>
        </div>

        {/* Rapport Word — actif */}
        <div
          onClick={() => downloadReport("word")}
          style={{
            background: "var(--bubble-ai)",
            border: "1px solid var(--border-color)",
            borderRadius: "14px",
            padding: "16px 14px",
            cursor: sessionId ? "pointer" : "not-allowed",
            position: "relative",
            minHeight: "90px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            opacity: sessionId ? 1 : 0.5,
            transition: "background .15s",
          }}
          onMouseEnter={e => { if (sessionId) (e.currentTarget as HTMLElement).style.background = "var(--bubble-user)"; }}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "var(--bubble-ai)"}
        >
          <span style={{ display: "inline-flex", alignItems: "center" }}>
            <svg width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" x2="8" y1="13" y2="13" />
              <line x1="16" x2="8" y1="17" y2="17" />
              <line x1="10" x2="8" y1="9" y2="9" />
            </svg>
          </span>
          <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)", marginTop: "10px", lineHeight: 1.3 }}>
            Rapport Word
          </div>
        </div>

        {/* Dashboard Interactif */}
        <div
          onClick={() => { if (sessionId) window.open(`/dashboard/${sessionId}`, "_blank"); }}
          style={{
            background: "var(--bubble-ai)",
            border: "1px solid var(--border-color)",
            borderRadius: "14px",
            padding: "16px 14px",
            cursor: sessionId ? "pointer" : "not-allowed",
            position: "relative",
            minHeight: "90px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            opacity: sessionId ? 1 : 0.5,
            transition: "background .15s",
          }}
          onMouseEnter={e => { if (sessionId) (e.currentTarget as HTMLElement).style.background = "var(--bubble-user)"; }}
          onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = "var(--bubble-ai)"}
        >
          <span style={{ display: "inline-flex", alignItems: "center" }}>
            <svg width="24" height="24" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
              <path d="M2.4 13.2A1.2 1.2 0 0 1 3.6 12H6a1.2 1.2 0 0 1 1.2 1.2v6A1.2 1.2 0 0 1 6 20.4H3.6a1.2 1.2 0 0 1-1.2-1.2v-6Zm7.2-4.8a1.2 1.2 0 0 1 1.2-1.2h2.4a1.2 1.2 0 0 1 1.2 1.2v10.8a1.2 1.2 0 0 1-1.2 1.2h-2.4a1.2 1.2 0 0 1-1.2-1.2V8.4Zm7.2-3.6A1.2 1.2 0 0 1 18 3.6h2.4a1.2 1.2 0 0 1 1.2 1.2v14.4a1.2 1.2 0 0 1-1.2 1.2H18a1.2 1.2 0 0 1-1.2-1.2V4.8Z"></path>
            </svg>
          </span>
          <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)", marginTop: "10px", lineHeight: 1.3 }}>
            Dashboard interactif
          </div>
        </div>

        {/* Cartes bientôt */}
        {STUDIO_ITEMS_SOON.map((item, i) => (
          <div key={i} style={{
            background: "var(--bubble-ai)",
            border: "1px solid var(--border-color)",
            borderRadius: "14px",
            padding: "16px 14px",
            cursor: "not-allowed",
            position: "relative",
            minHeight: "90px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
          }}>
            <span style={{
              position: "absolute", top: "10px", right: "10px",
              fontSize: "9px", background: "var(--border-color)",
              border: "1px solid var(--border-color)", color: "var(--text-muted)",
              padding: "2px 7px", borderRadius: "4px", letterSpacing: ".04em",
            }}>BIENTÔT</span>
            <span style={{ fontSize: "20px" }}>{item.icon}</span>
            <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-muted)", marginTop: "10px", lineHeight: 1.3 }}>
              {item.label}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}