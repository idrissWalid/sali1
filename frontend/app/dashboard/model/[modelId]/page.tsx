"use client";

import React, { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { toggleTheme, useTheme } from "@/hooks/use-theme";
import { AlertTriangle, ArrowLeft, Crosshair, Sun, Moon, Loader2 } from 'lucide-react';
import TimeSeriesModelView, { TimeSeriesReport } from '@/app/components/TimeSeriesModelView';
import SupervisedModelView, { SupervisedReport } from '@/app/components/SupervisedModelView';

interface ModelInfo {
  id: string;
  name: string;
  type: string;
  features: string[];
  metrics: Record<string, unknown>;
  created_at: string;
}

export default function ModelDashboard() {
  const { modelId } = useParams<{ modelId: string }>();
  const [model, setModel] = useState<ModelInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState<Record<string, string>>({});
  const [prediction, setPrediction] = useState<unknown>(null);
  const [predicting, setPredicting] = useState(false);
  const router = useRouter();
  const theme = useTheme();

  useEffect(() => {
    async function fetchModelInfo() {
      try {
        setLoading(true);
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
        const res = await fetch(`${apiUrl}/api/models/info/${modelId}`);
        if (!res.ok) throw new Error("Erreur lors de la récupération des détails du modèle");
        const data = await res.json();
        setModel(data);

        // Initialize form
        const initialData: Record<string, string> = {};
        if (data.features) {
          data.features.forEach((feat: string) => {
            initialData[feat] = "";
          });
        }
        setFormData(initialData);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Erreur de récupération");
      } finally {
        setLoading(false);
      }
    }

    fetchModelInfo();
  }, [modelId]);

  const handlePredict = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setPredicting(true);
      setPrediction(null);

      // Parse numerical values if possible
      const parsedFeatures: Record<string, string | number> = {};
      Object.keys(formData).forEach(key => {
        const val = formData[key];
        if (!isNaN(Number(val)) && val.trim() !== "") {
          parsedFeatures[key] = Number(val);
        } else {
          parsedFeatures[key] = val;
        }
      });

      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/models/${modelId}/predict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ features: parsedFeatures })
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Erreur de prédiction");
      }

      const data = await res.json();
      setPrediction(data.prediction);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Erreur lors de la prédiction");
    } finally {
      setPredicting(false);
    }
  };

  if (loading) {
    return (
      <div className="dashboard-shell flex h-screen w-full items-center justify-center bg-gray-50 dark:bg-[#111] text-gray-900 dark:text-gray-100">
        <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
          <Loader2 className="h-4 w-4 animate-spin" /> Chargement du modèle…
        </div>
      </div>
    );
  }

  if (error || !model) {
    return (
      <div className="dashboard-shell flex h-screen w-full items-center justify-center bg-gray-50 dark:bg-[#111] text-gray-900 dark:text-gray-100">
        <div className="max-w-sm rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1a1a1a] p-6 text-center shadow-sm">
          <h1 className="mb-2 text-lg font-bold text-red-500">Erreur</h1>
          <p className="text-sm text-gray-500 dark:text-gray-400">{error}</p>
          <button
            onClick={() => router.back()}
            className="mt-5 inline-flex items-center gap-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1a1a1a] px-4 py-2 text-sm font-medium shadow-sm transition-colors hover:bg-gray-50 dark:hover:bg-[#222]"
          >
            <ArrowLeft size={16} /> Retour
          </button>
        </div>
      </div>
    );
  }

  // Les modèles de séries temporelles ont une vue dédiée (rapport gates +
  // prévision) au lieu du formulaire de prédiction feature-par-feature.
  if (model.type === "timeseries") {
    return (
      <TimeSeriesModelView
        model={{ ...model, metrics: model.metrics as TimeSeriesReport }}
        onBack={() => router.back()}
      />
    );
  }

  // Les modèles issus du tournoi supervisé exposent le détail des hypothèses
  // vérifiées et la comparaison des candidats, que le formulaire de prédiction
  // générique ne saurait montrer.
  if (model.type === "supervised") {
    return (
      <SupervisedModelView
        model={{ ...model, metrics: model.metrics as SupervisedReport }}
        onBack={() => router.back()}
      />
    );
  }

  // Repli générique (clustering, analyse factorielle, anciens modèles) : mêmes
  // couleurs, rayons et ombres que le dashboard de données, pour que l'ensemble
  // des vues de modèles forme un système visuel cohérent.
  const champ = "w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#222] px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:border-blue-500 transition-colors";

  return (
    <div className="dashboard-shell min-h-screen w-full bg-gray-50 dark:bg-[#111] text-gray-900 dark:text-gray-100 font-sans">
      <div className="mx-auto w-full max-w-5xl px-5 sm:px-8 md:px-10 py-8 flex flex-col gap-6">
        {/* En-tête */}
        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => router.back()}
            className="flex items-center gap-2 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1a1a1a] px-4 py-2 text-sm font-medium shadow-sm transition-colors hover:bg-gray-50 dark:hover:bg-[#222]"
          >
            <ArrowLeft size={16} /> Retour
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-2xl sm:text-3xl font-bold tracking-tight">{model.name}</h1>
            <p className="mt-0.5 text-sm text-gray-500 dark:text-gray-400">Dashboard prédictif</p>
          </div>
          <button
            onClick={toggleTheme}
            className="grid place-items-center rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1a1a1a] p-2.5 shadow-sm transition-colors hover:bg-gray-50 dark:hover:bg-[#222]"
          >
            {theme === "dark" ? <Sun className="w-4 h-4 text-gray-400" /> : <Moon className="w-4 h-4 text-gray-500" />}
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="md:col-span-1 flex flex-col gap-6">
            <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1a1a1a] p-6 shadow-sm">
              <h2 className="mb-4 border-b border-gray-100 dark:border-gray-800 pb-3 text-sm font-bold uppercase tracking-wide text-gray-600 dark:text-gray-300">
                Détails du modèle
              </h2>
              <div className="flex flex-col gap-3 text-sm">
                <div>
                  <span className="block text-gray-500 dark:text-gray-400">Type</span>
                  <span className="font-medium">{model.type}</span>
                </div>
                <div>
                  <span className="block text-gray-500 dark:text-gray-400">Créé le</span>
                  <span>{new Date(model.created_at).toLocaleString("fr-FR")}</span>
                </div>
              </div>
            </div>

            {model.metrics && Object.keys(model.metrics).length > 0 && (
              <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1a1a1a] p-6 shadow-sm">
                <h2 className="mb-4 border-b border-gray-100 dark:border-gray-800 pb-3 text-sm font-bold uppercase tracking-wide text-gray-600 dark:text-gray-300">
                  Performances
                </h2>
                <div className="flex flex-col gap-2">
                  {Object.entries(model.metrics).map(([k, v]) => (
                    <div
                      key={k}
                      className="flex items-center justify-between gap-3 rounded-lg bg-gray-50 dark:bg-[#222] px-3 py-2 text-sm"
                    >
                      <span className="text-gray-500 dark:text-gray-400">{k}</span>
                      <span className="font-mono text-gray-900 dark:text-gray-100">
                        {typeof v === 'number' ? v.toFixed(4) : String(v)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="md:col-span-2">
            <div className="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1a1a1a] p-6 shadow-sm">
              <h2 className="mb-5 flex items-center gap-2 border-b border-gray-100 dark:border-gray-800 pb-3 text-sm font-bold uppercase tracking-wide text-gray-600 dark:text-gray-300">
                <Crosshair size={15} strokeWidth={1.8} /> Simulation
              </h2>

              <form onSubmit={handlePredict} className="flex flex-col gap-4">
                {model.features && model.features.length > 0 ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {model.features.map(feat => (
                      <label key={feat} className="flex flex-col gap-1.5">
                        <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">{feat}</span>
                        <input
                          type="text"
                          required
                          value={formData[feat] || ""}
                          onChange={e => setFormData({ ...formData, [feat]: e.target.value })}
                          className={champ}
                          placeholder={`Valeur pour ${feat}`}
                        />
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="flex items-center gap-2 rounded-lg border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-900/10 p-4 text-sm text-amber-700 dark:text-amber-400">
                    <AlertTriangle size={17} className="shrink-0" />
                    Ce modèle ne spécifie pas de caractéristiques d&apos;entrée claires. Les prédictions peuvent échouer.
                  </div>
                )}

                <div className="mt-2 pt-4 border-t border-gray-100 dark:border-gray-800">
                  <button
                    type="submit"
                    disabled={predicting}
                    className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 disabled:opacity-60"
                  >
                    {predicting ? <><Loader2 size={15} className="animate-spin" /> Calcul en cours…</> : "Générer la prédiction"}
                  </button>
                </div>
              </form>

              {prediction !== null && (
                <div className="mt-6 rounded-xl border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-[#202020] p-5">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                    Résultat de la prédiction
                  </h3>
                  <div className="mt-1 break-all font-mono text-2xl font-bold">
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
