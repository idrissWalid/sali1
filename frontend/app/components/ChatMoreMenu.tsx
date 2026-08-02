"use client";

import { useEffect, useRef } from "react";
import { Download } from "@/components/animate-ui/icons/download";

interface Message {
  role: "user" | "assistant";
  text: string;
}

interface ChatMoreMenuProps {
  isOpen: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLButtonElement | null>;
  messages: Message[];
  onClearChat: () => void;
}

export default function ChatMoreMenu({ isOpen, onClose, anchorRef, messages, onClearChat }: ChatMoreMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (
        isOpen &&
        menuRef.current &&
        !menuRef.current.contains(e.target as Node) &&
        anchorRef.current &&
        !anchorRef.current.contains(e.target as Node)
      ) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, [isOpen, onClose, anchorRef]);

  if (!isOpen) return null;

  const exportMarkdown = () => {
    if (messages.length === 0) {
      alert("Aucun message à exporter !");
      return;
    }
    const mdContent = messages
      .map((msg) => {
        const sender = msg.role === "user" ? "### Utilisateur" : "### Assistant IA";
        return `${sender}\n\n${msg.text}\n\n---\n`;
      })
      .join("\n");

    const blob = new Blob([`# Historique de Discussion\n\n${mdContent}`], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "discussion_analyse.md";
    a.click();
    URL.revokeObjectURL(url);
    onClose();
  };

  const exportHTML = () => {
    if (messages.length === 0) {
      alert("Aucun message à exporter !");
      return;
    }
    const htmlMessages = messages
      .map((msg) => {
        const isUser = msg.role === "user";
        const sender = isUser ? "Utilisateur" : "Assistant IA";
        const bg = isUser ? "#e8f0fe" : "#f1f3f4";
        const align = isUser ? "flex-end" : "flex-start";
        const color = "#202124";

        return `
          <div style="display: flex; justify-content: ${align}; margin-bottom: 20px;">
            <div style="max-width: 70%; padding: 14px 18px; border-radius: 16px; background-color: ${bg}; color: ${color}; font-family: sans-serif; font-size: 14px; line-height: 1.6;">
              <strong style="display: block; margin-bottom: 6px; font-size: 12px; opacity: 0.7;">${sender}</strong>
              <div>${msg.text.replace(/\n/g, "<br>")}</div>
            </div>
          </div>
        `;
      })
      .join("");

    const fullHTML = `
      <!DOCTYPE html>
      <html lang="fr">
      <head>
        <meta charset="UTF-8">
        <title>Discussion Exportée</title>
      </head>
      <body style="background-color: #f8f9fa; padding: 40px; font-family: system-ui, -apple-system, sans-serif;">
        <div style="max-width: 800px; margin: 0 auto; background: #ffffff; padding: 30px; border-radius: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);">
          <h1 style="font-size: 22px; color: #202124; margin-top: 0; margin-bottom: 30px; border-bottom: 1px solid #e0e0e0; padding-bottom: 15px;">Historique de Discussion</h1>
          ${htmlMessages}
        </div>
      </body>
      </html>
    `;

    const blob = new Blob([fullHTML], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "discussion_analyse.html";
    a.click();
    URL.revokeObjectURL(url);
    onClose();
  };

  return (
    <div
      ref={menuRef}
      style={{
        position: "absolute",
        top: "56px",
        right: "24px",
        width: "200px",
        background: "var(--bg-panel)",
        border: "1px solid var(--border-color)",
        borderRadius: "12px",
        boxShadow: "0 8px 24px rgba(0, 0, 0, 0.15)",
        zIndex: 9999,
        padding: "8px",
        display: "flex",
        flexDirection: "column",
        gap: "4px",
        animation: "menu-slide-down 0.15s cubic-bezier(0.16, 1, 0.3, 1) forwards",
      }}
    >
      <style>{`
        @keyframes menu-slide-down {
          from { transform: translateY(-8px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }
      `}</style>

      {[
        { label: "Exporter en Markdown", action: exportMarkdown, isDownload: true },
        { label: "Exporter en HTML", action: exportHTML, isDownload: true },
        {
          label: "Vider la discussion",
          action: () => {
            if (confirm("Voulez-vous vraiment effacer tous les messages ?")) {
              onClearChat();
            }
            onClose();
          },
          isRed: true,
        },
      ].map((item, idx) => (
        <button
          key={idx}
          onClick={item.action}
          style={{
            padding: "8px 12px",
            borderRadius: "8px",
            border: "none",
            background: "transparent",
            color: item.isRed ? "#ea4335" : "var(--text-main)",
            fontSize: "13px",
            textAlign: "left",
            display: "flex",
            alignItems: "center",
            gap: "8px",
            cursor: "pointer",
            transition: "background 0.15s",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bubble-ai)")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
        >
          {item.isDownload && <Download animateOnHover size={15} aria-hidden="true" />}
          {item.label}
        </button>
      ))}
    </div>
  );
}
