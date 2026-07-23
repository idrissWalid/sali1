"use client";

import { Check, FileText, Pencil, Plus, Table2, Trash2, X } from "lucide-react";
import { useState } from "react";
import type { SessionItem } from "../lib/types";

interface Props {
  sessions: SessionItem[];
  currentSessionId: string | null;
  onSelectSession: (id: string) => void;
  onDeleteSession: (id: string) => void;
  onRenameSession?: (id: string, title: string) => void;
  onNewSession: () => void;
}

function formatDate(dateString: string) {
  try {
    return new Date(dateString).toLocaleDateString("fr-FR", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateString;
  }
}

export default function HistoryPanel({ sessions, currentSessionId, onSelectSession, onDeleteSession, onRenameSession, onNewSession }: Props) {
  const [hovered, setHovered] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState("");

  const startEditing = (session: SessionItem) => {
    setEditingId(session.id);
    setEditingTitle(session.title || "");
  };

  const commitEditing = () => {
    if (editingId) onRenameSession?.(editingId, editingTitle);
    setEditingId(null);
  };

  const cancelEditing = () => setEditingId(null);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="shrink-0 px-4 pb-2 pt-3">
        <button
          onClick={onNewSession}
          className="flex w-full items-center justify-center gap-2 rounded-md border py-2.5 text-[13px] font-medium transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
          style={{ borderColor: "var(--border-color)", background: "transparent", color: "var(--text-main)" }}
        >
          <Plus size={15} strokeWidth={1.8} /> Nouvelle discussion
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2.5 pb-3">
        {sessions.length === 0 ? (
          <div className="px-4 py-10 text-center text-[13px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
            Aucune discussion enregistrée.
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {sessions.map((session) => {
              const isActive = session.id === currentSessionId;
              const isHovered = session.id === hovered;
              const isEditing = session.id === editingId;
              return (
                <div
                  key={session.id}
                  onMouseEnter={() => setHovered(session.id)}
                  onMouseLeave={() => setHovered(null)}
                  onClick={() => onSelectSession(session.id)}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md border px-3 py-2.5 transition-colors"
                  style={{
                    background: isActive ? "var(--accent-soft)" : isHovered ? "var(--bubble-ai)" : "transparent",
                    borderColor: isActive ? "var(--accent)" : "transparent",
                  }}
                >
                  <div className="grid size-7 shrink-0 place-items-center rounded-md border" style={{ borderColor: "var(--border-muted)" }}>
                    {session.type === "tabular" ? (
                      <Table2 size={13} style={{ color: "var(--accent)" }} />
                    ) : (
                      <FileText size={13} style={{ color: "var(--text-muted)" }} />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
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
                        className="w-full rounded border px-1.5 py-0.5 text-[13px] font-medium outline-none"
                        style={{ color: "var(--text-main)", background: "var(--bg-app)", borderColor: "var(--accent)" }}
                      />
                    ) : (
                      <div
                        className="truncate text-[13px]"
                        style={{ color: "var(--text-main)", fontWeight: isActive ? 600 : 500 }}
                      >
                        {session.title || "Sans titre"}
                      </div>
                    )}
                    <div className="mt-0.5 text-[11px]" style={{ color: "var(--text-dim)" }}>
                      {formatDate(session.created_at)}
                    </div>
                  </div>
                  {isEditing ? (
                    <div className="flex shrink-0 gap-0.5">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          commitEditing();
                        }}
                        className="rounded p-1.5 transition-colors hover:bg-[var(--bubble-ai)]"
                        style={{ color: "var(--text-muted)" }}
                      >
                        <Check size={13} strokeWidth={1.8} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          cancelEditing();
                        }}
                        className="rounded p-1.5 transition-colors hover:bg-[var(--bubble-ai)] hover:text-[var(--danger)]"
                        style={{ color: "var(--text-muted)" }}
                      >
                        <X size={13} strokeWidth={1.8} />
                      </button>
                    </div>
                  ) : (isHovered || isActive) && (
                    <div className="flex shrink-0 gap-0.5">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          startEditing(session);
                        }}
                        className="rounded p-1.5 transition-colors hover:bg-[var(--bubble-ai)]"
                        style={{ color: "var(--text-muted)" }}
                      >
                        <Pencil size={13} strokeWidth={1.8} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onDeleteSession(session.id);
                        }}
                        className="rounded p-1.5 transition-colors hover:bg-[var(--bubble-ai)] hover:text-[var(--danger)]"
                        style={{ color: "var(--text-muted)" }}
                      >
                        <Trash2 size={13} strokeWidth={1.8} />
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
