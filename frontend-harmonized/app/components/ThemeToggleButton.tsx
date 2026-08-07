"use client";

import { motion } from "framer-motion";
import type { MouseEventHandler } from "react";

type ThemeToggleButtonProps = {
  isDark: boolean;
  onClick: MouseEventHandler<HTMLButtonElement>;
};

export default function ThemeToggleButton({ isDark, onClick }: ThemeToggleButtonProps) {
  return (
    <button
      aria-label={isDark ? "Activer le thème clair" : "Activer le thème sombre"}
      className="theme-toggle-button"
      onClick={onClick}
      title={isDark ? "Thème clair" : "Thème sombre"}
      type="button"
    >
      <svg aria-hidden="true" fill="none" strokeLinecap="round" viewBox="0 0 32 32">
        <motion.circle
          animate={{ r: isDark ? 7 : 9 }}
          cx="16"
          cy="16"
          fill="currentColor"
          transition={{ duration: 0.35, ease: "easeInOut" }}
        />
        <motion.circle
          animate={{ cx: isDark ? 27 : 20, cy: isDark ? 5 : 11, r: isDark ? 0 : 7 }}
          fill="var(--bg-panel)"
          transition={{ duration: 0.35, ease: "easeInOut" }}
        />
        <motion.g
          initial={{ opacity: isDark ? 1 : 0, scale: isDark ? 1 : 0.5 }}
          animate={{ opacity: isDark ? 1 : 0, scale: isDark ? 1 : 0.5 }}
          stroke="currentColor"
          strokeWidth="2"
          style={{ originX: "16px", originY: "16px" }}
          transition={{ duration: 0.35, ease: "easeInOut" }}
        >
          <path d="M16 2.5v3M16 26.5v3M2.5 16h3M26.5 16h3M6.45 6.45l2.1 2.1M23.45 23.45l2.1 2.1M25.55 6.45l-2.1 2.1M8.55 23.45l-2.1 2.1" />
        </motion.g>
      </svg>
    </button>
  );
}
