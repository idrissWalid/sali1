"use client";

import { Check, Copy, Loader2, Mail, MessageSquare, Users } from "lucide-react";
import { useState } from "react";
import Modal from "./Modal";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  sourcesCount: number;
}

export default function ShareModal({ isOpen, onClose, sourcesCount }: Props) {
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

  const copy = () => {
    if (!shareLink) return;
    navigator.clipboard.writeText(shareLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Partager la session" maxWidth="480px">
      <div className="flex flex-col gap-5">
        <div className="flex items-center justify-around rounded-lg border px-4 py-3.5" style={{ borderColor: "var(--border-muted)", background: "var(--bubble-ai)" }}>
          <div className="text-center">
            <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>Sources</div>
            <div className="mt-1 text-[20px] font-semibold" style={{ color: "var(--text-main)" }}>{sourcesCount}</div>
          </div>
          <div className="h-8 w-px" style={{ background: "var(--border-color)" }} />
          <div className="text-center">
            <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>Statut</div>
            <div className="mt-1 flex items-center gap-1.5 text-[13px] font-medium" style={{ color: "var(--accent)" }}>
              <span className="size-1.5 rounded-full" style={{ background: "var(--accent)" }} /> Active
            </div>
          </div>
          <div className="h-8 w-px" style={{ background: "var(--border-color)" }} />
          <div className="text-center">
            <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>Hébergeur</div>
            <div className="mt-1 text-[13px] font-medium" style={{ color: "var(--text-main)" }}>Local</div>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="text-[13px] font-medium" style={{ color: "var(--text-main)" }}>Lien de partage public</div>
          <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>
            Toute personne disposant de ce lien pourra lire l&rsquo;analyse et la discussion sans modifier vos fichiers.
          </div>

          {shareLink ? (
            <div className="mt-1.5 flex gap-2.5">
              <input readOnly value={shareLink} className="flex-1 rounded-md border px-3.5 py-2.5 text-[13px] outline-none" style={{ borderColor: "var(--border-color)", background: "var(--bg-app)", color: "var(--text-main)" }} />
              <button
                onClick={copy}
                className="flex items-center gap-1.5 rounded-md px-5 text-[13px] font-medium text-white"
                style={{ background: copied ? "#22c55e" : "var(--accent)" }}
              >
                {copied ? <><Check size={15} /> Copié</> : <><Copy size={15} /> Copier</>}
              </button>
            </div>
          ) : (
            <button
              onClick={generateLink}
              disabled={generating}
              className="mt-1.5 flex w-full items-center justify-center gap-2 rounded-md py-3 text-[13px] font-medium text-white"
              style={{ background: "var(--accent)" }}
            >
              {generating ? <><Loader2 size={16} className="animate-spin" /> Génération du lien...</> : "Créer un lien de partage"}
            </button>
          )}
        </div>

        <div className="mt-1.5 flex flex-col gap-2.5">
          <div className="text-[12px] font-medium" style={{ color: "var(--text-muted)" }}>Ou partager directement via</div>
          <div className="flex gap-2.5">
            {[
              { name: "Email", icon: Mail, bg: "rgba(59,130,246,0.12)", color: "#60a5fa" },
              { name: "Slack", icon: MessageSquare, bg: "var(--bubble-ai)", color: "var(--text-main)" },
              { name: "Teams", icon: Users, bg: "rgba(52,211,153,0.14)", color: "var(--accent)" },
            ].map((ch) => {
              const Icon = ch.icon;
              return (
                <button
                  key={ch.name}
                  onClick={() => alert(`Lien partagé vers ${ch.name} !`)}
                  className="flex flex-1 items-center justify-center gap-2 rounded-md py-2.5 text-[13px] font-medium transition-opacity hover:opacity-85"
                  style={{ background: ch.bg, color: ch.color }}
                >
                  <Icon size={16} strokeWidth={1.8} /> {ch.name}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </Modal>
  );
}
