"use client";

import { useState } from "react";
import Modal from "./Modal";

interface ChatSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function ChatSettingsModal({ isOpen, onClose }: ChatSettingsModalProps) {
  const [typingSpeed, setTypingSpeed] = useState(40);
  const [systemPrompt, setSystemPrompt] = useState("Tu es un analyste de données expert. Réponds de façon concise et structure tes réponses.");
  const [autoScroll, setAutoScroll] = useState(true);

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Paramètres de discussion" maxWidth="480px">
      <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
        
        {/* Typing speed selector */}
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--text-muted)" }}>
              {"Vitesse de frappe de l'IA ("}{typingSpeed}{" ms)"}
            </label>
            <span style={{ fontSize: "11px", color: "var(--text-dim)" }}>
              Délai par caractère
            </span>
          </div>
          <input
            type="range"
            min="10"
            max="100"
            step="5"
            value={typingSpeed}
            onChange={(e) => setTypingSpeed(parseInt(e.target.value))}
            style={{ width: "100%", accentColor: "var(--accent-color)", cursor: "pointer" }}
          />
        </div>

        {/* System Prompt Customization */}
        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
          <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--text-muted)" }}>
            {"Instructions système de l'IA"}
          </label>
          <textarea
            value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)}
            rows={4}
            style={{
              padding: "10px 14px",
              borderRadius: "12px",
              border: "1px solid var(--border-color)",
              background: "var(--bg-app)",
              color: "var(--text-main)",
              fontSize: "13px",
              fontFamily: "inherit",
              resize: "none",
              outline: "none",
            }}
          />
        </div>

        {/* Autoscroll checkbox */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "4px" }}>
          <div>
            <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)" }}>Défilement automatique</div>
            <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>Défiler vers le bas à la réception des messages</div>
          </div>
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
            style={{ width: "18px", height: "18px", accentColor: "var(--accent-color)", cursor: "pointer" }}
          />
        </div>

      </div>

      {/* Footer */}
      <div style={{
        display: "flex",
        justifyContent: "flex-end",
        gap: "12px",
        borderTop: "1px solid var(--border-muted)",
        paddingTop: "18px",
        marginTop: "16px"
      }}>
        <button
          onClick={onClose}
          style={{
            padding: "8px 20px",
            borderRadius: "18px",
            border: "1.5px solid var(--border-color)",
            color: "var(--text-muted)",
            fontSize: "13px",
            fontWeight: 500,
            background: "transparent",
            cursor: "pointer",
          }}
        >
          Annuler
        </button>
        <button
          onClick={() => {
            alert("Paramètres de la discussion mis à jour !");
            onClose();
          }}
          style={{
            padding: "8px 24px",
            borderRadius: "18px",
            border: "none",
            color: "var(--bg-app)",
            background: "var(--accent-color)",
            fontSize: "13px",
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          Valider
        </button>
      </div>
    </Modal>
  );
}
