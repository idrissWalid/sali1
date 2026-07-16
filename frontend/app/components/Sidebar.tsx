"use client";

import { useState } from "react";
import { FileText, Plus, Table2, Trash2 } from "lucide-react";

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
  onNewSession: () => void;
  hideHeader?: boolean;
  style?: React.CSSProperties;
}

export default function Sidebar({
  sessions,
  currentSessionId,
  onSelectSession,
  onDeleteSession,
  onNewSession,
  hideHeader = false,
  style,
}: Props) {
  const [hoveredSessionId, setHoveredSessionId] = useState<string | null>(null);

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
    <div style={{
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
          fontFamily: "'Google Sans',sans-serif",
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
            title="Nouvelle session"
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
        {sessions.length === 0 ? (
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

              return (
                <div
                  key={session.id}
                  onMouseEnter={() => setHoveredSessionId(session.id)}
                  onMouseLeave={() => setHoveredSessionId(null)}
                  onClick={() => onSelectSession(session.id)}
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
                    <div style={{
                      fontSize: "11px",
                      color: "var(--text-dim)",
                      marginTop: "2px",
                    }}>
                      {formatDate(session.created_at)}
                    </div>
                  </div>

                  {/* Actions (Delete button on hover) */}
                  {(isHovered || isActive) && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onDeleteSession(session.id);
                      }}
                      title="Supprimer la discussion"
                      style={{
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
                      }}
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
