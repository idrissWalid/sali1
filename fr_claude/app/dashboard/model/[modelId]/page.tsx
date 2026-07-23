"use client";

import { AlertTriangle, ArrowLeft, Crosshair } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getModelInfo, predictModel } from "../../../lib/api";
import type { ModelInfo } from "../../../lib/types";

export default function ModelDashboard() {
  const { modelId } = useParams<{ modelId: string }>();
  const router = useRouter();
  const [model, setModel] = useState<ModelInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [prediction, setPrediction] = useState<unknown>(null);
  const [predicting, setPredicting] = useState(false);

  useEffect(() => {
    if (!modelId) return;
    getModelInfo(modelId)
      .then((data) => {
        setModel(data);
        const init: Record<string, string> = {};
        (data.features || []).forEach((f) => { init[f] = ""; });
        setFormData(init);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Erreur de récupération"))
      .finally(() => setLoading(false));
  }, [modelId]);

  const handlePredict = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!modelId) return;
    setPredicting(true);
    setPrediction(null);
    try {
      const parsed: Record<string, string | number> = {};
      Object.entries(formData).forEach(([key, val]) => {
        parsed[key] = val.trim() !== "" && !isNaN(Number(val)) ? Number(val) : val;
      });
      setPrediction(await predictModel(modelId, parsed));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Erreur lors de la prédiction");
    } finally {
      setPredicting(false);
    }
  };

  if (loading) {
    return <div className="p-8 text-center" style={{ color: "var(--text-main)", background: "var(--bg-app)" }}>Chargement du Dashboard...</div>;
  }

  if (error || !model) {
    return (
      <div className="min-h-screen p-8 text-center" style={{ background: "var(--bg-app)", color: "var(--text-main)" }}>
        <h1 className="mb-4 text-[24px]" style={{ color: "var(--danger)" }}>Erreur</h1>
        <p>{error}</p>
        <button onClick={() => router.back()} className="mt-4 rounded-lg border px-4 py-2" style={{ borderColor: "var(--border-color)" }}>Retour</button>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-8" style={{ background: "var(--bg-app)", color: "var(--text-main)" }}>
      <div className="mx-auto max-w-4xl">
        <div className="mb-8 flex items-center gap-4">
          <button onClick={() => router.back()} className="flex items-center gap-2 rounded-md border px-4 py-2 transition-colors hover:bg-[var(--bubble-ai)]" style={{ borderColor: "var(--border-color)" }}>
            <ArrowLeft size={16} /> Retour
          </button>
          <h1 className="font-serif text-[24px] font-medium">Dashboard Prédictif : {model.name}</h1>
        </div>

        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          <div className="space-y-6 md:col-span-1">
            <div className="rounded-lg border p-6" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }}>
              <h2 className="mb-4 border-b pb-2 text-[16px] font-semibold" style={{ borderColor: "var(--border-muted)" }}>Détails du modèle</h2>
              <div className="space-y-3 text-[13px]">
                <div>
                  <span className="block" style={{ color: "var(--text-muted)" }}>Type :</span>
                  <span className="font-medium">{model.type}</span>
                </div>
                <div>
                  <span className="block" style={{ color: "var(--text-muted)" }}>Créé le :</span>
                  <span>{new Date(model.created_at).toLocaleString()}</span>
                </div>
              </div>
            </div>

            {model.metrics && Object.keys(model.metrics).length > 0 && (
              <div className="rounded-lg border p-6" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }}>
                <h2 className="mb-4 border-b pb-2 text-[16px] font-semibold" style={{ borderColor: "var(--border-muted)" }}>Performances</h2>
                <div className="space-y-2">
                  {Object.entries(model.metrics).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between rounded-lg p-2" style={{ background: "var(--bubble-ai)" }}>
                      <span className="text-[13px]" style={{ color: "var(--text-muted)" }}>{k}</span>
                      <span className="font-mono text-[13px]">{typeof v === "number" ? v.toFixed(4) : String(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="md:col-span-2">
            <div className="rounded-lg border p-6" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }}>
              <h2 className="mb-6 flex items-center gap-2 text-[18px] font-semibold">
                <Crosshair size={19} strokeWidth={1.8} /> Simulation en temps réel
              </h2>

              <form onSubmit={handlePredict} className="space-y-4">
                {model.features && model.features.length > 0 ? (
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    {model.features.map((feat) => (
                      <div key={feat}>
                        <label className="mb-1 block text-[13px] font-medium" style={{ color: "var(--text-muted)" }}>{feat}</label>
                        <input
                          type="text"
                          required
                          value={formData[feat] || ""}
                          onChange={(e) => setFormData({ ...formData, [feat]: e.target.value })}
                          placeholder={`Valeur pour ${feat}`}
                          className="w-full rounded-lg border p-2 outline-none transition-colors focus:border-[var(--accent)]"
                          style={{ borderColor: "var(--border-color)", background: "var(--bg-app)", color: "var(--text-main)" }}
                        />
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="flex items-center gap-2 rounded-lg border p-4 text-[13px]" style={{ borderColor: "#f59e0b", background: "rgba(245,158,11,0.1)", color: "#f59e0b" }}>
                    <AlertTriangle size={17} /> Ce modèle ne spécifie pas de caractéristiques d&apos;entrée claires. Les prédictions peuvent échouer.
                  </div>
                )}

                <div className="mt-6 border-t pt-4" style={{ borderColor: "var(--border-muted)" }}>
                  <button
                    type="submit"
                    disabled={predicting}
                    className="w-full rounded-md py-3 font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
                    style={{ background: "var(--accent)" }}
                  >
                    {predicting ? "Calcul en cours..." : "Générer la prédiction"}
                  </button>
                </div>
              </form>

              {prediction !== null && (
                <div className="mt-8 rounded-lg border p-6" style={{ borderColor: "var(--accent)", background: "var(--accent-soft)" }}>
                  <h3 className="mb-2 text-[12px] font-medium uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>Résultat de la prédiction</h3>
                  <div className="break-all font-mono text-[26px] font-bold">
                    {Array.isArray(prediction) ? JSON.stringify(prediction[0]) : JSON.stringify(prediction)}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
