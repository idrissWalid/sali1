"use client";

import { Download, LayoutDashboard, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { listTrainedModels, modelDownloadUrl } from "../lib/api";
import type { ModelInfo } from "../lib/types";
import Modal from "./Modal";

interface Props {
  sessionId: string | null;
  isOpen: boolean;
  onClose: () => void;
}

export default function ModelsModal({ sessionId, isOpen, onClose }: Props) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    if (!isOpen || !sessionId) return;
    setLoading(true);
    setError(null);
    listTrainedModels(sessionId)
      .then(setModels)
      .catch((err) => setError(err instanceof Error ? err.message : "Erreur lors de la récupération des modèles"))
      .finally(() => setLoading(false));
  }, [isOpen, sessionId]);

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Modèles entraînés" maxWidth="760px">
      <div className="mb-4 flex items-center gap-2 text-[12px]" style={{ color: "var(--text-muted)" }}>
        <span className="grid size-7 place-items-center rounded-md border" style={{ borderColor: "var(--border-muted)" }}>
          <Sparkles size={14} strokeWidth={1.8} />
        </span>
        Retrouvez, explorez ou téléchargez les modèles créés pour cette session.
      </div>

      <div className="flex max-h-[58dvh] flex-col gap-3 overflow-y-auto pr-1">
        {loading ? (
          <div className="py-8 text-center text-[13px]" style={{ color: "var(--text-muted)" }}>Chargement des modèles...</div>
        ) : error ? (
          <div className="py-8 text-center text-[13px]" style={{ color: "var(--danger)" }}>{error}</div>
        ) : models.length === 0 ? (
          <div className="py-8 text-center text-[13px]" style={{ color: "var(--text-muted)" }}>Aucun modèle entraîné dans cette session.</div>
        ) : (
          models.map((model) => (
            <div key={model.id} className="rounded-lg border p-5" style={{ borderColor: "var(--border-color)", background: "var(--bubble-ai)" }}>
              <div className="mb-2 flex items-start justify-between">
                <div>
                  <h3 className="text-[15px] font-semibold" style={{ color: "var(--text-main)" }}>{model.name}</h3>
                  <span className="mt-2 inline-flex rounded-md border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)", color: "var(--text-muted)" }}>
                    {model.type}
                  </span>
                </div>
                <div className="ml-4 text-right text-[11px]" style={{ color: "var(--text-dim)" }}>
                  {new Date(model.created_at).toLocaleString()}
                </div>
              </div>

              {model.metrics && Object.keys(model.metrics).length > 0 && (
                <div className="mb-3">
                  <div className="mb-2 text-[12px] font-medium" style={{ color: "var(--text-muted)" }}>Métriques</div>
                  <div className="grid grid-cols-2 gap-2">
                    {Object.entries(model.metrics).map(([key, value]) => (
                      <div key={key} className="flex justify-between rounded-lg border p-2 text-[12px]" style={{ borderColor: "var(--border-muted)", background: "var(--bg-panel)" }}>
                        <span style={{ color: "var(--text-muted)" }}>{key}</span>
                        <span className="font-mono" style={{ color: "var(--text-main)" }}>{typeof value === "number" ? value.toFixed(4) : String(value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {model.features && model.features.length > 0 && (
                <div className="mb-4">
                  <div className="mb-2 text-[12px] font-medium" style={{ color: "var(--text-muted)" }}>Variables d&apos;entrée ({model.features.length})</div>
                  <div className="flex flex-wrap gap-1">
                    {model.features.map((feat) => (
                      <span key={feat} className="rounded-md border px-2 py-1 text-[11px]" style={{ borderColor: "var(--border-muted)", background: "var(--bg-panel)", color: "var(--text-muted)" }}>
                        {feat}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                <button
                  onClick={() => { router.push(`/dashboard/model/${model.id}`); onClose(); }}
                  className="flex-1 rounded-md px-4 py-2.5 text-[13px] font-medium text-white transition-opacity hover:opacity-90"
                  style={{ background: "var(--accent)" }}
                >
                  <LayoutDashboard size={16} strokeWidth={1.8} className="mr-1.5 inline-block align-text-bottom" /> Créer Dashboard
                </button>
                <button
                  onClick={() => window.open(modelDownloadUrl(model.id), "_blank")}
                  className="flex-1 rounded-md border px-4 py-2.5 text-[13px] font-medium transition-colors hover:bg-[var(--bubble-ai)]"
                  style={{ borderColor: "var(--border-color)", color: "var(--text-main)" }}
                >
                  <Download size={16} strokeWidth={1.8} className="mr-1.5 inline-block align-text-bottom" /> Télécharger (.pkl)
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </Modal>
  );
}
