"use client";

import { useState } from "react";
import { Check, FileText, Pencil, Plus, Table2, Trash2, X } from "lucide-react";

interface SessionItem {
  id: string;
  title: string;
  type: string;
  filename?: string;
  created_at: string;
}

interface Props {
  sessions: SessionItem[];
  currentSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onRenameSession?: (sessionId: string, title: string) => void;
  onNewSession: () => void;
  hideHeader?: boolean;
  style?: React.CSSProperties;
  /** Distingue « pas encore chargé » et « le chargement a échoué » du vrai vide.
   *  Sans ça, les trois cas produisaient le même écran. */
  state?: "loading" | "ready" | "error";
  onRetry?: () => void;
}

const actionButtonStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "var(--text-muted)",
  fontSize: "16px",
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  width: "24px",
  height: "24px",
  borderRadius: "50%",
  transition: "all 0.2s",
};

export default function Sidebar({
  sessions,
  currentSessionId,
  onSelectSession,
  onDeleteSession,
  onRenameSession,
  onNewSession,
  hideHeader = false,
  style,
  state = "ready",
  onRetry,
}: Props) {
  const [hoveredSessionId, setHoveredSessionId] = useState<string | null>(null);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  const startEditing = (session: SessionItem) => {
    setEditingSessionId(session.id);
    setEditingTitle(session.title || "");
  };

  const commitEditing = () => {
    if (editingSessionId) {
      onRenameSession?.(editingSessionId, editingTitle);
    }
    setEditingSessionId(null);
  };

  const cancelEditing = () => {
    setEditingSessionId(null);
  };

  const formatDate = (dateString: string) => {
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString("fr-FR", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return dateString;
    }
  };

  return (
    <div className="history-panel" style={{
      height: "100%",
      display: "flex",
      flexDirection: "column",
      background: "transparent",
      overflow: "hidden",
      ...style
    }}>
      {/* Header */}
      {!hideHeader ? (
        <div style={{
          padding: "16px 20px 14px",
          fontFamily: "var(--font-google-sans), sans-serif",
          fontSize: "16px",
          fontWeight: 500,
          color: "var(--text-main)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}>
          <span>Historique</span>
          <button
            onClick={onNewSession}
            title="Nouvelle session" aria-label="Nouvelle session"
            style={{
              background: "none",
              border: "none",
              color: "var(--text-muted)",
              fontSize: "20px",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: "28px",
              height: "28px",
              borderRadius: "50%",
              transition: "all 0.2s",
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = "var(--bubble-ai)";
              e.currentTarget.style.color = "var(--text-main)";
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = "none";
              e.currentTarget.style.color = "var(--text-muted)";
            }}
          >
            <Plus size={17} strokeWidth={1.8} />
          </button>
        </div>
      ) : (
        <div style={{
          padding: "12px 16px 8px",
          display: "flex",
          justifyContent: "center",
          flexShrink: 0,
        }}>
          <button
            onClick={onNewSession}
            style={{
              width: "100%",
              padding: "10px",
              borderRadius: "10px",
              border: "1px solid var(--border-color)",
              color: "var(--text-main)",
              background: "var(--bubble-ai)",
              fontSize: "13px",
              fontWeight: 500,
              cursor: "pointer",
              transition: "all 0.15s",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
            }}
            onMouseEnter={e => {
              e.currentTarget.style.borderColor = "var(--accent-color)";
              e.currentTarget.style.background = "var(--accent-soft)";
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = "var(--border-color)";
              e.currentTarget.style.background = "var(--bubble-ai)";
            }}
          >
            <Plus size={15} strokeWidth={1.8} /> Nouvelle discussion
          </button>
        </div>
      )}

      {/* Sessions list */}
      <div style={{
        flex: 1,
        overflowY: "auto",
        padding: "4px 8px 12px",
      }}>
        {state === "loading" && sessions.length === 0 ? (
          // Squelettes plutôt qu'un vide trompeur pendant le chargement.
          <div aria-busy="true" aria-label="Chargement des discussions"
               style={{ display: "flex", flexDirection: "column", gap: "4px", padding: "4px 0" }}>
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="frontend-loading-block"
                   style={{ height: "44px", borderRadius: "10px", opacity: 1 - i * 0.18 }} />
            ))}
          </div>
        ) : state === "error" ? (
          <div role="alert" style={{
            display: "flex", flexDirection: "column", alignItems: "center", gap: "10px",
            padding: "32px 14px", color: "var(--text-muted)", fontSize: "13px",
            lineHeight: 1.6, textAlign: "center",
          }}>
            <span>Impossible de charger vos discussions.</span>
            <span style={{ color: "var(--text-dim)", fontSize: "12px" }}>
              Le serveur est peut-être injoignable.
            </span>
            {onRetry && (
              <button
                onClick={onRetry}
                style={{
                  minHeight: "36px", padding: "0 14px", borderRadius: "9px",
                  border: "1px solid var(--border-color)", color: "var(--text-main)",
                  background: "var(--bubble-ai)", fontSize: "12px", fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Réessayer
              </button>
            )}
          </div>
        ) : sessions.length === 0 ? (
          <div style={{
            textAlign: "center",
            color: "var(--text-dim)",
            fontSize: "13px",
            padding: "40px 10px",
            lineHeight: 1.6,
          }}>
            Aucune discussion enregistrée.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
            {sessions.map((session) => {
              const isActive = session.id === currentSessionId;
              const isHovered = session.id === hoveredSessionId;
              const isEditing = session.id === editingSessionId;

              return (
                <div
                  key={session.id}
                  // La ligne n'était qu'un `div onClick` : sans `tabIndex` ni
                  // gestion clavier, aucune session ne pouvait être ouverte sans
                  // souris.
                  role="button"
                  tabIndex={0}
                  aria-current={isActive ? "true" : undefined}
                  aria-label={`Ouvrir la discussion « ${session.title} »`}
                  onMouseEnter={() => setHoveredSessionId(session.id)}
                  onMouseLeave={() => setHoveredSessionId(null)}
                  // Les actions de la ligne n'apparaissaient qu'au survol, donc
                  // jamais au clavier. `onFocus`/`onBlur` remontent en React
                  // (focusin/focusout) : la ligne s'ouvre aussi quand l'un de ses
                  // boutons prend le focus, et ne se referme que si le focus quitte
                  // la ligne entière.
                  onFocus={() => setHoveredSessionId(session.id)}
                  onBlur={(e) => {
                    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                      setHoveredSessionId(null);
                    }
                  }}
                  onClick={() => onSelectSession(session.id)}
                  onKeyDown={(e) => {
                    // Les boutons d'action enfants gèrent leurs propres touches.
                    if (e.target !== e.currentTarget) return;
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelectSession(session.id);
                    }
                  }}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "10px",
                    padding: "10px 12px",
                    borderRadius: "10px",
                    cursor: "pointer",
                    background: isActive
                      ? "var(--accent-soft)"
                      : isHovered
                        ? "var(--bubble-ai)"
                        : "transparent",
                    border: `1px solid ${isActive ? "var(--accent-color)" : "transparent"}`,
                    transition: "all 0.2s",
                    position: "relative",
                  }}
                >
                  {/* Icon */}
                  <div style={{
                    width: "28px",
                    height: "28px",
                    borderRadius: "6px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "14px",
                    flexShrink: 0,
                    background: session.type === "tabular"
                      ? "rgba(52,168,83,0.12)"
                      : "rgba(234,67,53,0.12)",
                  }}>
                    {session.type === "tabular" ? <Table2 size={15} color="#72d39b" /> : <FileText size={15} color="#e59a9a" />}
                  </div>

                  {/* Title & Metadata */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {isEditing ? (
                      <input
                        autoFocus
                        value={editingTitle}
                        onClick={(e) => e.stopPropagation()}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            commitEditing();
                          } else if (e.key === "Escape") {
                            e.preventDefault();
                            cancelEditing();
                          }
                        }}
                        onBlur={commitEditing}
                        style={{
                          width: "100%",
                          fontSize: "13px",
                          fontWeight: 500,
                          color: "var(--text-main)",
                          background: "var(--bg-app)",
                          border: "1px solid var(--accent-color)",
                          borderRadius: "6px",
                          padding: "2px 6px",
                          outline: "none",
                        }}
                      />
                    ) : (
                      <div style={{
                        fontSize: "13px",
                        fontWeight: isActive ? 600 : 500,
                        color: "var(--text-main)",
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}>
                        {session.title || "Sans titre"}
                      </div>
                    )}
                    <div style={{
                      fontSize: "11px",
                      color: "var(--text-dim)",
                      marginTop: "2px",
                    }}>
                      {formatDate(session.created_at)}
                    </div>
                  </div>

                  {/* Actions */}
                  {isEditing ? (
                    <div style={{ display: "flex", gap: "2px", flexShrink: 0 }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          commitEditing();
                        }}
                        title="Valider" aria-label="Valider"
                        style={actionButtonStyle}
                        onMouseEnter={e => {
                          e.currentTarget.style.background = "rgba(52,168,83,0.15)";
                          e.currentTarget.style.color = "#34a853";
                        }}
                        onMouseLeave={e => {
                          e.currentTarget.style.background = "none";
                          e.currentTarget.style.color = "var(--text-muted)";
                        }}
                      >
                        <Check size={14} strokeWidth={1.8} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          cancelEditing();
                        }}
                        title="Annuler" aria-label="Annuler"
                        style={actionButtonStyle}
                        onMouseEnter={e => {
                          e.currentTarget.style.background = "rgba(234,67,53,0.15)";
                          e.currentTarget.style.color = "#ea4335";
                        }}
                        onMouseLeave={e => {
                          e.currentTarget.style.background = "none";
                          e.currentTarget.style.color = "var(--text-muted)";
                        }}
                      >
                        <X size={14} strokeWidth={1.8} />
                      </button>
                    </div>
                  ) : (isHovered || isActive) && (
                    <div style={{ display: "flex", gap: "2px", flexShrink: 0 }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          startEditing(session);
                        }}
                        title="Renommer la discussion" aria-label="Renommer la discussion"
                        style={actionButtonStyle}
                        onMouseEnter={e => {
                          e.currentTarget.style.background = "var(--bubble-ai)";
                          e.currentTarget.style.color = "var(--text-main)";
                        }}
                        onMouseLeave={e => {
                          e.currentTarget.style.background = "none";
                          e.currentTarget.style.color = "var(--text-muted)";
                        }}
                      >
                        <Pencil size={14} strokeWidth={1.8} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteSession(session.id);
                        }}
                        title="Supprimer la discussion" aria-label="Supprimer la discussion"
                        style={actionButtonStyle}
                        onMouseEnter={e => {
                          e.currentTarget.style.background = "rgba(234,67,53,0.15)";
                          e.currentTarget.style.color = "#ea4335";
                        }}
                        onMouseLeave={e => {
                          e.currentTarget.style.background = "none";
                          e.currentTarget.style.color = "var(--text-muted)";
                        }}
                      >
                        <Trash2 size={14} strokeWidth={1.8} />
                      </button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
