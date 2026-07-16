"use client";

import { useState } from "react";
import Modal from "./Modal";
import { Check, Copy, Mail, MessageSquare, Users } from "lucide-react";

interface ShareModalProps {
  isOpen: boolean;
  onClose: () => void;
  sourcesCount: number;
}

export default function ShareModal({ isOpen, onClose, sourcesCount }: ShareModalProps) {
  const [copied, setCopied] = useState(false);
  const [shareLink, setShareLink] = useState("");
  const [generating, setGenerating] = useState(false);

  const generateLink = () => {
    setGenerating(true);
    setTimeout(() => {
      const mockId = Math.random().toString(36).substring(2, 10);
      setShareLink(`https://nocodedata.intelligence/share/${mockId}`);
      setGenerating(false);
    }, 800);
  };

  const copyToClipboard = () => {
    if (!shareLink) return;
    navigator.clipboard.writeText(shareLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Partager la session" maxWidth="480px">
      <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
        
        {/* Statistics info */}
        <div style={{
          background: "var(--bubble-ai)",
          border: "1px solid var(--border-muted)",
          borderRadius: "14px",
          padding: "14px 16px",
          display: "flex",
          justifyContent: "space-around",
          alignItems: "center",
        }}>
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Sources</div>
            <div style={{ fontSize: "20px", fontWeight: 600, color: "var(--text-main)", marginTop: "4px" }}>
              {sourcesCount}
            </div>
          </div>
          <div style={{ width: "1px", height: "30px", background: "var(--border-color)" }} />
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Statut</div>
            <div style={{ fontSize: "13px", fontWeight: 500, color: "#34a853", marginTop: "4px", display: "flex", alignItems: "center", gap: "4px" }}>
              <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#34a853" }} />
              Active
            </div>
          </div>
          <div style={{ width: "1px", height: "30px", background: "var(--border-color)" }} />
          <div style={{ textAlign: "center" }}>
            <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>Hébergeur</div>
            <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)", marginTop: "4px" }}>
              Local
            </div>
          </div>
        </div>

        {/* Action area */}
        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
          <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)" }}>Lien de partage public</div>
          <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>
            {"Toute personne disposant de ce lien pourra lire l'analyse et la discussion sans modifier vos fichiers."}
          </div>

          {shareLink ? (
            <div style={{ display: "flex", gap: "10px", marginTop: "6px" }}>
              <input
                readOnly
                value={shareLink}
                style={{
                  flex: 1,
                  padding: "10px 14px",
                  borderRadius: "12px",
                  border: "1px solid var(--border-color)",
                  background: "var(--bg-app)",
                  color: "var(--text-main)",
                  fontSize: "13px",
                  outline: "none",
                }}
              />
              <button
                onClick={copyToClipboard}
                style={{
                  padding: "0 20px",
                  borderRadius: "12px",
                  border: "none",
                  background: copied ? "#34a853" : "var(--accent-color)",
                  color: "var(--bg-app)",
                  fontSize: "13px",
                  fontWeight: 500,
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  transition: "background 0.2s",
                }}
              >
                {copied ? <><Check size={15} /> Copié</> : <><Copy size={15} /> Copier</>}
              </button>
            </div>
          ) : (
            <button
              onClick={generateLink}
              disabled={generating}
              style={{
                width: "100%",
                padding: "12px",
                borderRadius: "12px",
                border: "none",
                background: "var(--accent-color)",
                color: "var(--bg-app)",
                fontWeight: 500,
                fontSize: "13px",
                cursor: "pointer",
                marginTop: "6px",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
              }}
            >
              {generating ? (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" className="animate-hourglass">
                    <path d="M5 2h14M5 22h14M19 2v4c0 3-2 5-5 5v2c3 0 5 2 5 5v4M5 2v4c0 3 2 5 5 5v2c-3 0-5 2-5 5v4" />
                  </svg>
                  Génération du lien...
                </>
              ) : (
                "Créer un lien de partage"
              )}
            </button>
          )}
        </div>

        {/* Social channels */}
        <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginTop: "6px" }}>
          <div style={{ fontSize: "12px", fontWeight: 500, color: "var(--text-muted)" }}>Ou partager directement via</div>
          <div style={{ display: "flex", gap: "10px" }}>
            {[
              { name: "Email", icon: Mail, color: "rgba(26, 115, 232, 0.1)", textColor: "#1a73e8" },
              { name: "Slack", icon: MessageSquare, color: "rgba(74, 21, 75, 0.1)", textColor: "#b998c4" },
              { name: "Teams", icon: Users, color: "rgba(70, 78, 184, 0.1)", textColor: "#9fa8ff" },
            ].map((ch) => {
              const Icon = ch.icon;
              return <button
                key={ch.name}
                onClick={() => alert(`Lien partagé vers ${ch.name} !`)}
                style={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "8px",
                  padding: "10px",
                  borderRadius: "10px",
                  border: "none",
                  background: ch.color,
                  color: ch.textColor,
                  fontSize: "13px",
                  fontWeight: 500,
                  cursor: "pointer",
                  transition: "opacity 0.2s",
                }}
                onMouseEnter={(e) => e.currentTarget.style.opacity = "0.85"}
                onMouseLeave={(e) => e.currentTarget.style.opacity = "1"}
              >
                <Icon size={16} strokeWidth={1.8} />
                <span>{ch.name}</span>
              </button>
            })}
          </div>
        </div>

      </div>
    </Modal>
  );
}
