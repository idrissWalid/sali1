"use client";

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import Modal from './Modal';
import { API_URL } from '@/lib/api';
import { LayoutDashboard, Sparkles } from 'lucide-react';
import { Download } from '@/components/animate-ui/icons/download';

interface ModelInfo {
  id: string;
  name: string;
  type: string;
  features: string[];
  metrics: Record<string, unknown>;
  created_at: string;
}

interface ModelsModalProps {
  sessionId: string | null;
  onClose: () => void;
  isOpen?: boolean;
}

export default function ModelsModal({ sessionId, onClose, isOpen = true }: ModelsModalProps) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    async function fetchModels() {
      try {
        setLoading(true);
        const apiUrl = API_URL;
        const res = await fetch(`${apiUrl}/api/models/${sessionId}`);
        if (!res.ok) throw new Error("Erreur de récupération des modèles");
        const data = await res.json();
        setModels(data.models || []);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erreur lors de la récupération des modèles");
      } finally {
        setLoading(false);
      }
    }

    if (isOpen) {
      fetchModels();
    }
  }, [sessionId, isOpen]);

  if (!isOpen) return null;

  const handleDownload = (modelId: string) => {
    const apiUrl = API_URL;
    window.open(`${apiUrl}/api/models/${modelId}/download`, '_blank');
  };

  const handleDashboard = (modelId: string) => {
    router.push(`/dashboard/model/${modelId}`);
    onClose();
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Modèles entraînés" maxWidth="760px">
        <div className="flex items-center gap-2 pb-4 text-xs text-[var(--text-muted)]">
          <span className="grid size-7 place-items-center rounded-full bg-[var(--accent-soft)]"><Sparkles size={14} strokeWidth={1.8} /></span>
          Retrouvez, explorez ou téléchargez les modèles créés pour cette session.
        </div>
        <div className="max-h-[58dvh] space-y-3 overflow-y-auto pr-1">
          {loading ? (
            <div className="text-center text-gray-400 py-8">Chargement des modèles...</div>
          ) : error ? (
            <div className="text-center text-red-400 py-8">{error}</div>
          ) : models.length === 0 ? (
            <div className="text-center text-gray-400 py-8">Aucun modèle entraîné dans cette session.</div>
          ) : (
            <div className="space-y-3">
              {models.map(model => (
                <div key={model.id} className="rounded-2xl border border-[var(--border-color)] bg-[var(--bubble-ai)] p-4 sm:p-5">
                  <div className="flex justify-between items-start mb-2">
                    <div>
                      <h3 className="text-[15px] font-semibold text-[var(--text-main)]">{model.name}</h3>
                      <span className="mt-2 inline-flex rounded-md border border-[var(--border-color)] bg-[var(--bg-panel)] px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--text-muted)]">
                        {model.type}
                      </span>
                    </div>
                    <div className="ml-4 text-right text-[11px] text-[var(--text-dim)]">
                      {new Date(model.created_at).toLocaleString()}
                    </div>
                  </div>

                  {model.type === "timeseries" ? (
                    <TimeSeriesMetricsSummary metrics={model.metrics} />
                  ) : model.metrics && Object.keys(model.metrics).length > 0 && (
                    <div className="mb-3">
                      <div className="mb-2 text-xs font-medium text-[var(--text-muted)]">Métriques</div>
                      <div className="grid grid-cols-2 gap-2">
                        {Object.entries(model.metrics).map(([key, value]) => (
                          <div key={key} className="flex justify-between rounded-lg border border-[var(--border-muted)] bg-[var(--bg-panel)] p-2 text-xs">
                            <span className="text-[var(--text-muted)]">{key}</span>
                            <span className="font-mono text-[var(--text-main)]">{typeof value === 'number' ? value.toFixed(4) : String(value)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {model.type !== "timeseries" && model.features && model.features.length > 0 && (
                    <div className="mb-4">
                      <div className="mb-2 text-xs font-medium text-[var(--text-muted)]">{"Variables d'entrée ("}{model.features.length}{")"}</div>
                      <div className="flex flex-wrap gap-1">
                        {model.features.map(feat => (
                          <span key={feat} className="rounded-md border border-[var(--border-muted)] bg-[var(--bg-panel)] px-2 py-1 text-[11px] text-[var(--text-muted)]">
                            {feat}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="mt-4 flex flex-col gap-2 sm:flex-row">
                    <button
                      onClick={() => handleDashboard(model.id)}
                      className="flex-1 rounded-xl bg-[var(--accent-color)] px-4 py-2.5 text-sm font-medium text-[var(--bg-app)] transition-all hover:brightness-110"
                    >
                      <LayoutDashboard size={16} strokeWidth={1.8} className="inline-block mr-1.5 align-text-bottom" /> {model.type === "timeseries" ? "Voir le dashboard" : "Créer Dashboard"}
                    </button>
                    {model.type !== "timeseries" && (
                      <button
                        onClick={() => handleDownload(model.id)}
                        className="flex-1 rounded-xl border border-[var(--border-color)] bg-transparent px-4 py-2.5 text-sm font-medium text-[var(--text-main)] transition-colors hover:bg-[var(--bg-panel)]"
                      >
                        <Download animateOnHover size={16} strokeWidth={1.8} className="inline-block mr-1.5 align-text-bottom" /> Télécharger (.pkl)
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
    </Modal>
  );
}

// Résumé compact d'un modèle de série temporelle dans la liste (statut + gates
// clés), au lieu du dump brut du rapport imbriqué.
function TimeSeriesMetricsSummary({ metrics }: { metrics: Record<string, unknown> }) {
  const r = (metrics || {}) as {
    statut_final?: string;
    modele_retenu?: { type?: string; ordre?: number[]; ordre_saisonnier?: number[] | null };
    gate_2_validation_out_of_sample?: { mape_pct?: number; statut?: string };
    gate_1_diagnostics_residus?: { statut?: string };
  };
  const modele = r.modele_retenu || {};
  const label = modele.ordre
    ? `${modele.type ?? "SARIMA"} (${modele.ordre.join(",")})${modele.ordre_saisonnier ? `×(${modele.ordre_saisonnier.join(",")})` : ""}`
    : (modele.type ?? "TimeCopilot");
  const mape = r.gate_2_validation_out_of_sample?.mape_pct;
  const badge = (s?: string) =>
    s === "PASS" ? "text-green-500" : s === "FAIL" ? "text-red-500" : "text-[var(--text-muted)]";
  return (
    <div className="mb-3 grid grid-cols-2 gap-2 text-xs">
      <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--bg-panel)] p-2">
        <div className="text-[var(--text-muted)]">Modèle</div>
        <div className="font-mono text-[var(--text-main)]">{label}</div>
      </div>
      <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--bg-panel)] p-2">
        <div className="text-[var(--text-muted)]">Statut</div>
        <div className="font-medium text-[var(--text-main)]">{r.statut_final ?? "—"}</div>
      </div>
      <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--bg-panel)] p-2">
        <div className="text-[var(--text-muted)]">MAPE</div>
        <div className="font-mono text-[var(--text-main)]">{typeof mape === "number" ? `${mape.toFixed(2)}%` : "—"}</div>
      </div>
      <div className="rounded-lg border border-[var(--border-muted)] bg-[var(--bg-panel)] p-2">
        <div className="text-[var(--text-muted)]">Gates</div>
        <div className="font-medium">
          <span className={badge(r.gate_1_diagnostics_residus?.statut)}>G1</span>{" · "}
          <span className={badge(r.gate_2_validation_out_of_sample?.statut)}>G2</span>
        </div>
      </div>
    </div>
  );
}
