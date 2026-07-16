"use client";

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, ArrowLeft, Crosshair } from 'lucide-react';

interface ModelInfo {
  id: string;
  name: string;
  type: string;
  features: string[];
  metrics: Record<string, unknown>;
  created_at: string;
}

export default function ModelDashboard({ params }: { params: { modelId: string } }) {
  const [model, setModel] = useState<ModelInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  const [formData, setFormData] = useState<Record<string, string>>({});
  const [prediction, setPrediction] = useState<unknown>(null);
  const [predicting, setPredicting] = useState(false);
  const router = useRouter();

  useEffect(() => {
    async function fetchModelInfo() {
      try {
        setLoading(true);
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
        const res = await fetch(`${apiUrl}/api/models/info/${params.modelId}`);
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
  }, [params.modelId]);

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
      const res = await fetch(`${apiUrl}/api/models/${params.modelId}/predict`, {
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
    return <div className="p-8 text-center text-white">Chargement du Dashboard...</div>;
  }

  if (error || !model) {
    return (
      <div className="p-8 text-center text-white">
        <h1 className="text-2xl text-red-400 mb-4">Erreur</h1>
        <p>{error}</p>
        <button onClick={() => router.back()} className="mt-4 px-4 py-2 bg-[#333342] rounded">Retour</button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#111116] p-8 text-white">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-4 mb-8">
          <button onClick={() => router.back()} className="px-4 py-2 bg-[#1e1e24] hover:bg-[#26262e] rounded-lg transition-colors border border-[#2d2d3a]">
            <ArrowLeft size={16} className="inline mr-2" /> Retour
          </button>
          <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-indigo-400">
            Dashboard Prédictif : {model.name}
          </h1>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
          <div className="md:col-span-1 space-y-6">
            <div className="bg-[#1e1e24] border border-[#2d2d3a] rounded-xl p-6 shadow-xl">
              <h2 className="text-xl font-semibold mb-4 text-gray-200 border-b border-[#2d2d3a] pb-2">Détails du Modèle</h2>
              <div className="space-y-3 text-sm">
                <div>
                  <span className="text-gray-400 block">Type :</span>
                  <span className="font-medium">{model.type}</span>
                </div>
                <div>
                  <span className="text-gray-400 block">Créé le :</span>
                  <span>{new Date(model.created_at).toLocaleString()}</span>
                </div>
              </div>
            </div>

            {model.metrics && Object.keys(model.metrics).length > 0 && (
              <div className="bg-[#1e1e24] border border-[#2d2d3a] rounded-xl p-6 shadow-xl">
                <h2 className="text-xl font-semibold mb-4 text-gray-200 border-b border-[#2d2d3a] pb-2">Performances</h2>
                <div className="space-y-2">
                  {Object.entries(model.metrics).map(([k, v]) => (
                    <div key={k} className="flex justify-between items-center bg-[#26262e] p-2 rounded">
                      <span className="text-gray-400 text-sm">{k}</span>
                      <span className="font-mono">{typeof v === 'number' ? v.toFixed(4) : String(v)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="md:col-span-2">
            <div className="bg-[#1e1e24] border border-[#2d2d3a] rounded-xl p-6 shadow-xl">
              <h2 className="text-xl font-semibold mb-6 text-gray-200 flex items-center gap-2">
                <Crosshair size={20} strokeWidth={1.8} /> Simulation en temps réel
              </h2>
              
              <form onSubmit={handlePredict} className="space-y-4">
                {model.features && model.features.length > 0 ? (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    {model.features.map(feat => (
                      <div key={feat}>
                        <label className="block text-sm font-medium text-gray-400 mb-1">{feat}</label>
                        <input
                          type="text"
                          required
                          value={formData[feat] || ""}
                          onChange={e => setFormData({ ...formData, [feat]: e.target.value })}
                          className="w-full bg-[#111116] border border-[#333342] rounded p-2 text-white focus:outline-none focus:border-indigo-500 transition-colors"
                          placeholder={`Valeur pour ${feat}`}
                        />
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-yellow-400 text-sm p-4 bg-yellow-900/20 border border-yellow-900/50 rounded-lg">
                    <AlertTriangle size={17} className="inline mr-2 align-text-bottom" /> Ce modèle ne spécifie pas de caractéristiques d&apos;entrée claires. Les prédictions peuvent échouer.
                  </div>
                )}
                
                <div className="pt-4 mt-6 border-t border-[#2d2d3a]">
                  <button
                    type="submit"
                    disabled={predicting}
                    className={`w-full py-3 rounded-lg font-medium text-white transition-all ${
                      predicting 
                        ? "bg-indigo-600/50 cursor-not-allowed" 
                        : "bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 shadow-lg"
                    }`}
                  >
                    {predicting ? "Calcul en cours..." : "Générer la prédiction"}
                  </button>
                </div>
              </form>

              {prediction !== null && (
                <div className="mt-8 p-6 bg-gradient-to-br from-[#26262e] to-[#1e1e24] border border-indigo-500/30 rounded-xl">
                  <h3 className="text-gray-400 text-sm font-medium uppercase tracking-wider mb-2">Résultat de la prédiction</h3>
                  <div className="text-3xl font-bold text-white font-mono break-all">
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
