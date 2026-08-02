"use client";

import { useEffect, useRef } from "react";

interface AvatarMenuProps {
  isOpen: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLButtonElement | null>;
}

export default function AvatarMenu({ isOpen, onClose, anchorRef }: AvatarMenuProps) {
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

  return (
    <div
      ref={menuRef}
      style={{
        position: "absolute",
        top: "60px",
        right: "20px",
        width: "280px",
        background: "var(--bg-panel)",
        border: "1px solid var(--border-color)",
        borderRadius: "16px",
        boxShadow: "0 10px 30px rgba(0, 0, 0, 0.15)",
        zIndex: 9999,
        padding: "16px",
        display: "flex",
        flexDirection: "column",
        gap: "14px",
        animation: "menu-slide-down 0.2s cubic-bezier(0.16, 1, 0.3, 1) forwards",
      }}
    >
      <style>{`
        @keyframes menu-slide-down {
          from { transform: translateY(-8px); opacity: 0; }
          to { transform: translateY(0); opacity: 1; }
        }
      `}</style>

      {/* User Info */}
      <div style={{ display: "flex", alignItems: "center", gap: "12px", borderBottom: "1px solid var(--border-muted)", paddingBottom: "12px" }}>
        <div style={{
          width: "42px",
          height: "42px",
          borderRadius: "50%",
          background: "linear-gradient(135deg,#8ab4f8,#c58af9)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: "16px",
          fontWeight: 600,
          color: "#fff",
        }}>
          W
        </div>
        <div>
          <div style={{ fontSize: "14px", fontWeight: 500, color: "var(--text-main)" }}>Walid</div>
          <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>walid@example.com</div>
        </div>
      </div>

      {/* Storage Quota */}
      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px" }}>
          <span style={{ color: "var(--text-muted)" }}>Espace stockage</span>
          <span style={{ color: "var(--text-main)", fontWeight: 500 }}>2.4 Go / 10 Go</span>
        </div>
        <div style={{ width: "100%", height: "6px", background: "var(--border-muted)", borderRadius: "3px", overflow: "hidden" }}>
          <div style={{ width: "24%", height: "100%", background: "var(--accent-color)", borderRadius: "3px" }} />
        </div>
      </div>

      {/* Token Usage */}
      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "11px" }}>
          <span style={{ color: "var(--text-muted)" }}>Jetons IA restants</span>
          <span style={{ color: "var(--text-main)", fontWeight: 500 }}>426K / 500K</span>
        </div>
        <div style={{ width: "100%", height: "6px", background: "var(--border-muted)", borderRadius: "3px", overflow: "hidden" }}>
          <div style={{ width: "85%", height: "100%", background: "#c58af9", borderRadius: "3px" }} />
        </div>
      </div>

      {/* Menu links */}
      <div style={{
        display: "flex",
        flexDirection: "column",
        gap: "4px",
        borderTop: "1px solid var(--border-muted)",
        paddingTop: "8px",
        marginTop: "4px",
      }}>
        {[
          { label: "Mon compte", action: () => alert("Mon Compte") },
          { label: "Facturation", action: () => alert("Facturation") },
          { label: "Déconnexion", action: () => alert("Déconnexion"), isRed: true },
        ].map((item, idx) => (
          <button
            key={idx}
            onClick={item.action}
            style={{
              padding: "8px 10px",
              borderRadius: "8px",
              border: "none",
              background: "transparent",
              color: item.isRed ? "#ea4335" : "var(--text-main)",
              fontSize: "13px",
              textAlign: "left",
              cursor: "pointer",
              transition: "background 0.15s",
            }}
            onMouseEnter={(e) => e.currentTarget.style.background = "var(--bubble-ai)"}
            onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}
