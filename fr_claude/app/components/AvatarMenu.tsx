"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef } from "react";

interface AvatarMenuProps {
  isOpen: boolean;
  onClose: () => void;
  anchorRef: React.RefObject<HTMLElement | null>;
}

function Bar({ label, value, pct }: { label: string; value: string; pct: number }) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex justify-between text-[11px]">
        <span style={{ color: "var(--text-muted)" }}>{label}</span>
        <span className="font-medium" style={{ color: "var(--text-main)" }}>{value}</span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full" style={{ background: "var(--border-muted)" }}>
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: "var(--accent)" }} />
      </div>
    </div>
  );
}

export default function AvatarMenu({ isOpen, onClose, anchorRef }: AvatarMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
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
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [isOpen, onClose, anchorRef]);

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          ref={menuRef}
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.12 }}
          className="absolute right-0 top-[46px] z-[999] w-64 rounded-lg border p-4 shadow-xl"
          style={{ background: "var(--bg-panel)", borderColor: "var(--border-color)" }}
        >
          <div className="flex items-center gap-3 border-b pb-3" style={{ borderColor: "var(--border-muted)" }}>
            <div
              className="grid size-9 place-items-center rounded-full text-[13px] font-medium"
              style={{ background: "var(--accent)", color: "var(--accent-contrast)" }}
            >
              W
            </div>
            <div>
              <div className="text-[13px] font-medium" style={{ color: "var(--text-main)" }}>Walid</div>
              <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>walid@example.com</div>
            </div>
          </div>

          <div className="flex flex-col gap-3 py-3">
            <Bar label="Espace stockage" value="2.4 Go / 10 Go" pct={24} />
          </div>

          <div className="flex flex-col gap-0.5 border-t pt-2" style={{ borderColor: "var(--border-muted)" }}>
            {[
              { label: "Mon compte", action: () => alert("Mon Compte") },
              { label: "Déconnexion", action: () => alert("Déconnexion"), danger: true },
            ].map((item) => (
              <button
                key={item.label}
                onClick={item.action}
                className="rounded-md px-2.5 py-2 text-left text-[13px] transition-colors hover:bg-[var(--bubble-ai)]"
                style={{ color: item.danger ? "var(--danger)" : "var(--text-main)" }}
              >
                {item.label}
              </button>
            ))}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
