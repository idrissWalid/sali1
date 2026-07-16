"use client";

import { motion, useAnimate } from "motion/react";
import { useState } from "react";

interface Props {
  onSave: () => void | Promise<void>;
}

export default function StatefulSaveButton({ onSave }: Props) {
  const [scope, animate] = useAnimate();
  const [status, setStatus] = useState<"idle" | "loading" | "success">("idle");

  const handleClick = async () => {
    if (status !== "idle") return;
    setStatus("loading");
    await animate(".settings-save__loader", { width: 16, scale: 1, opacity: 1 }, { duration: 0.18 });

    await Promise.resolve(onSave());

    await animate(".settings-save__loader", { width: 0, scale: 0, opacity: 0 }, { duration: 0.16 });
    setStatus("success");
    await animate(".settings-save__check", { width: 16, scale: 1, opacity: 1 }, { duration: 0.2 });
  };

  return (
    <motion.button
      ref={scope}
      type="button"
      layout
      className={`settings-save-button${status === "success" ? " settings-save-button--success" : ""}`}
      onClick={handleClick}
      disabled={status !== "idle"}
    >
      <motion.span layout className="settings-save-button__content">
        <motion.svg
          className="settings-save__loader"
          initial={{ width: 0, scale: 0, opacity: 0 }}
          animate={status === "loading" ? { rotate: 360 } : { rotate: 0 }}
          transition={{ rotate: { duration: 0.7, repeat: Infinity, ease: "linear" } }}
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <path d="M12 3a9 9 0 1 0 9 9" stroke="currentColor" strokeWidth="2.3" strokeLinecap="round" />
        </motion.svg>
        <motion.svg
          className="settings-save__check"
          initial={{ width: 0, scale: 0, opacity: 0 }}
          viewBox="0 0 24 24"
          fill="none"
          aria-hidden="true"
        >
          <path d="M7.75 12.25 10.5 15l5.75-6" stroke="currentColor" strokeWidth="2.25" strokeLinecap="round" strokeLinejoin="round" />
        </motion.svg>
        <motion.span layout>{status === "loading" ? "Enregistrement" : status === "success" ? "Enregistré" : "Enregistrer"}</motion.span>
      </motion.span>
    </motion.button>
  );
}
