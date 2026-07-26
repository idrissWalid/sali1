"use client";

import React, { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { toggleTheme, useTheme } from "@/hooks/use-theme";
import { AlertTriangle, ArrowLeft, Crosshair, Sun, Moon, Loader2 } from 'lucide-react';
import TimeSeriesModelView, { TimeSeriesReport } from '@/app/components/TimeSeriesModelView';
import SupervisedModelView, { SupervisedReport } from '@/app/components/SupervisedModelView';
import { API_URL } from '@/lib/api';

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
        const apiUrl = API_URL;
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

      const apiUrl = API_URL;
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
      <div className="dashboard-container">
        
        {/* Header */}
        <div className="dashboard-header flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{model.name}</h1>
            <p className="text-gray-500 dark:text-gray-400 mt-1 flex items-center gap-2">
              <Crosshair className="w-4 h-4 text-blue-500" /> Modèle prédictif — Type : <span className="font-semibold text-gray-700 dark:text-gray-300">{model.type}</span>
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={toggleTheme}
              className="p-2 bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-[#333] transition flex items-center justify-center text-sm font-medium"
            >
              {theme === "dark" ? <Sun className="w-4 h-4 text-gray-400" /> : <Moon className="w-4 h-4 text-gray-500" />}
            </button>
            <button
              onClick={() => router.back()}
              className="px-4 py-2 bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-[#333] transition flex items-center gap-2 text-sm font-medium"
            >
              <ArrowLeft className="w-4 h-4" /> Retour
            </button>
          </div>
        </div>

        {/* Global Stats Overview */}
        <div className="dashboard-stats grid grid-cols-2 md:grid-cols-4">
          <StatCard title="Type de modèle" value={model.type} icon={Crosshair} />
          <StatCard title="Caractéristiques" value={model.features?.length ?? 0} icon={Crosshair} />
          <StatCard title="Date de création" value={new Date(model.created_at).toLocaleDateString("fr-FR")} icon={Crosshair} />
          <StatCard title="Statut" value="Actif" icon={Crosshair} />
        </div>

        <div className="dashboard-main-grid grid grid-cols-1 lg:grid-cols-3">
          {/* Left Column: Details & Performance */}
          <div className="lg:col-span-1 flex flex-col gap-6">
            <div className="dashboard-panel bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm">
              <h2 className="text-xl font-bold mb-4 border-b border-gray-100 dark:border-gray-800 pb-3">Détails du modèle</h2>
              <div className="flex flex-col gap-3 text-sm">
                <div className="flex justify-between py-1 border-b border-gray-50 dark:border-gray-800/50">
                  <span className="text-gray-500 dark:text-gray-400">Identifiant</span>
                  <span className="font-mono text-xs text-gray-700 dark:text-gray-300 truncate max-w-[150px]">{model.id}</span>
                </div>
                <div className="flex justify-between py-1 border-b border-gray-50 dark:border-gray-800/50">
                  <span className="text-gray-500 dark:text-gray-400">Type</span>
                  <span className="font-medium">{model.type}</span>
                </div>
                <div className="flex justify-between py-1">
                  <span className="text-gray-500 dark:text-gray-400">Créé le</span>
                  <span>{new Date(model.created_at).toLocaleString("fr-FR")}</span>
                </div>
              </div>
            </div>

            {model.metrics && Object.keys(model.metrics).length > 0 && (
              <div className="dashboard-panel bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm">
                <h2 className="text-xl font-bold mb-4 border-b border-gray-100 dark:border-gray-800 pb-3">Performances</h2>
                <div className="flex flex-col gap-2">
                  {Object.entries(model.metrics).map(([k, v]) => (
                    <div
                      key={k}
                      className="flex items-center justify-between gap-3 rounded-xl bg-gray-50 dark:bg-[#222] px-3.5 py-2.5 text-sm"
                    >
                      <span className="text-gray-500 dark:text-gray-400">{k}</span>
                      <span className="font-mono font-semibold text-gray-900 dark:text-gray-100">
                        {typeof v === 'number' ? v.toFixed(4) : String(v)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right Column: Simulation Form */}
          <div className="lg:col-span-2">
            <div className="dashboard-panel bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm">
              <h2 className="text-xl font-bold mb-5 flex items-center gap-2 border-b border-gray-100 dark:border-gray-800 pb-3">
                <Crosshair className="w-5 h-5 text-blue-500" /> Simulation &amp; Prédiction
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
                          className="w-full rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#222] px-3 py-2 text-sm text-gray-900 dark:text-gray-100 focus:outline-none focus:border-blue-500 transition-colors shadow-sm"
                          placeholder={`Valeur pour ${feat}`}
                        />
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="flex items-center gap-2 rounded-xl border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-900/10 p-4 text-sm text-amber-700 dark:text-amber-400">
                    <AlertTriangle className="w-5 h-5 shrink-0" />
                    Ce modèle ne spécifie pas de caractéristiques d&apos;entrée claires. Les prédictions peuvent échouer.
                  </div>
                )}

                <div className="mt-2 pt-4 border-t border-gray-100 dark:border-gray-800">
                  <button
                    type="submit"
                    disabled={predicting}
                    className="px-5 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-60 text-white font-semibold rounded-xl shadow-sm transition flex items-center gap-2 text-sm"
                  >
                    {predicting ? <><Loader2 className="w-4 h-4 animate-spin" /> Calcul en cours…</> : "Générer la prédiction"}
                  </button>
                </div>
              </form>

              {prediction !== null && (
                <div className="mt-6 rounded-2xl border border-blue-100 dark:border-blue-950 bg-blue-50/50 dark:bg-blue-900/20 p-5">
                  <h3 className="text-xs font-bold uppercase tracking-wide text-blue-600 dark:text-blue-400">
                    Résultat de la prédiction
                  </h3>
                  <div className="mt-2 break-all font-mono text-2xl font-bold text-gray-900 dark:text-gray-100">
                    {Array.isArray(prediction) ? JSON.stringify(prediction[0]) : JSON.stringify(prediction)}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

      </div>

      <style dangerouslySetInnerHTML={{__html: `
        .dashboard-shell {
          padding: 32px clamp(20px, 4vw, 72px) 48px;
        }
        .dashboard-container {
          width: min(100%, 1680px);
          margin: 0 auto;
          display: grid;
          gap: 24px;
        }
        .dashboard-header { gap: 24px; }
        .dashboard-stats { gap: 16px; }
        .dashboard-main-grid { gap: 24px; align-items: stretch; }
        .dashboard-panel { padding: 24px; }
        .dashboard-stat { min-height: 104px; padding: 20px; }
        @media (max-width: 640px) {
          .dashboard-shell { padding: 20px 14px 32px; }
          .dashboard-container { gap: 16px; }
          .dashboard-header { align-items: flex-start; flex-direction: column; gap: 16px; }
          .dashboard-header > div:last-child { width: 100%; }
          .dashboard-header button:last-child { flex: 1; justify-content: center; }
          .dashboard-stats { gap: 10px; }
          .dashboard-main-grid { gap: 16px; }
          .dashboard-panel { padding: 18px; }
        }
        .custom-scrollbar::-webkit-scrollbar {
          height: 6px;
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background-color: rgba(150, 150, 150, 0.3);
          border-radius: 10px;
        }
      `}} />
    </div>
  );
}

function StatCard({ title, value, icon: Icon }: { title: string, value: string | number, icon: React.ComponentType<{ className?: string }> }) {
  return (
    <div className="dashboard-stat bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm flex items-start gap-4">
      <div className="bg-gray-50 dark:bg-[#222] p-3 rounded-xl text-blue-500"><Icon className="w-6 h-6" /></div>
      <div className="min-w-0">
        <p className="text-sm text-gray-500 dark:text-gray-400 font-medium">{title}</p>
        <p className="text-2xl font-bold mt-1 truncate">{value}</p>
      </div>
    </div>
  );
}

