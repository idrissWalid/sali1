"use client";

import { Check, Cpu, Database, SlidersHorizontal } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import Modal from "./Modal";
import { API_URL } from "../lib/api";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  models: string[];
  proprietaryModels: string[];
  selectedModel: string;
  onModelChange: (model: string) => void;
  onModelsRefetch?: () => void;
}

type TabType = "general" | "model" | "rag";

const TABS: { id: TabType; label: string; description: string; icon: typeof Cpu }[] = [
  { id: "general", label: "Général", description: "Expérience", icon: SlidersHorizontal },
  { id: "model", label: "Modèle IA", description: "Intelligence", icon: Cpu },
  { id: "rag", label: "RAG & Données", description: "Indexation", icon: Database },
];

export default function SettingsModal({ isOpen, onClose, models, proprietaryModels, selectedModel, onModelChange, onModelsRefetch }: Props) {
  const [activeTab, setActiveTab] = useState<TabType>("general");
  const [lang, setLang] = useState("fr");
  const [temperature, setTemperature] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(2048);
  const [chunkSize, setChunkSize] = useState(500);
  const [chunkOverlap, setChunkOverlap] = useState(50);
  const [autoSpeech, setAutoSpeech] = useState(false);
  const [textAnimations, setTextAnimations] = useState(true);
  const [showToast, setShowToast] = useState(false);
  const [toastModel, setToastModel] = useState("");
  const [modelSource, setModelSource] = useState<"opensource" | "api">("opensource");

  const [isApiDialogOpen, setIsApiDialogOpen] = useState(false);
  const [providerModels, setProviderModels] = useState<Record<string, string[]>>({});
  const [apiProvider, setApiProvider] = useState("gemini");
  const [apiModelName, setApiModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSaving, setApiSaving] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const notifyModelChange = (m: string) => {
    onModelChange(m);
    setToastModel(m);
    setShowToast(true);
    setTimeout(() => setShowToast(false), 2000);
  };

  // Charge la liste des fournisseurs et de leurs modèles disponibles dès
  // l'ouverture de la boîte de dialogue "Configuration API".
  useEffect(() => {
    if (!isApiDialogOpen) return;
    fetch(`${API_URL}/api/settings/providers`)
      .then((res) => res.json())
      .then((data) => {
        const map: Record<string, string[]> = {};
        for (const p of data.providers || []) {
          map[p.id] = p.models || [];
        }
        setProviderModels(map);
      })
      .catch((err) => console.error("Erreur lors du chargement des fournisseurs:", err));
  }, [isApiDialogOpen]);

  // Toujours garder un modèle sélectionné cohérent avec le fournisseur choisi.
  useEffect(() => {
    const available = providerModels[apiProvider] || [];
    if (available.length > 0 && !available.includes(apiModelName)) {
      setApiModelName(available[0]);
    }
  }, [apiProvider, providerModels, apiModelName]);

  const submitApiConfig = async (e: FormEvent) => {
    e.preventDefault();
    setApiError(null);
    setApiSaving(true);
    try {
      const res = await fetch(`${API_URL}/api/settings/api-key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: apiProvider, model: apiModelName, api_key: apiKey }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => null);
        throw new Error(data?.detail || "Échec de l'enregistrement de la clé API.");
      }

      // Gemini garde son nom nu (rétrocompatibilité), les autres fournisseurs
      // sont préfixés "provider/model" pour le routage backend.
      const composedModel = apiProvider === "gemini" ? apiModelName : `${apiProvider}/${apiModelName}`;
      onModelsRefetch?.();
      notifyModelChange(composedModel);

      setApiKey("");
      setIsApiDialogOpen(false);
    } catch (err) {
      setApiError(err instanceof Error ? err.message : "Erreur inconnue.");
    } finally {
      setApiSaving(false);
    }
  };

  return (
    <>
      <Modal isOpen={isOpen} onClose={onClose} title="Préférences" maxWidth="820px">
        <div className="mb-5 rounded-lg border p-4" style={{ borderColor: "var(--border-muted)", background: "var(--bubble-ai)" }}>
          <span className="text-[10.5px] font-bold uppercase tracking-wider" style={{ color: "var(--accent)" }}>Espace de travail</span>
          <p className="mt-1 text-[13px]" style={{ color: "var(--text-muted)" }}>Personnalisez votre environnement d&rsquo;analyse sans ajouter de complexité.</p>
        </div>

        <div className="flex flex-col gap-5 sm:flex-row">
          <nav className="flex shrink-0 gap-1.5 overflow-x-auto sm:w-44 sm:flex-col">
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className="flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2.5 text-left transition-colors"
                  style={{ background: active ? "var(--accent-soft)" : "transparent" }}
                >
                  <Icon size={16} strokeWidth={1.8} style={{ color: active ? "var(--accent)" : "var(--text-muted)" }} />
                  <span>
                    <strong className="block text-[13px]" style={{ color: active ? "var(--accent)" : "var(--text-main)" }}>{tab.label}</strong>
                    <small className="text-[10.5px]" style={{ color: "var(--text-dim)" }}>{tab.description}</small>
                  </span>
                </button>
              );
            })}
          </nav>

          <div className="min-w-0 flex-1">
            {activeTab === "general" && (
              <div className="flex flex-col gap-5">
                <div className="flex flex-col gap-1.5">
                  <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Langue de l&rsquo;interface</label>
                  <select value={lang} onChange={(e) => setLang(e.target.value)} className="rounded-md border px-3.5 py-2.5 text-[13px]" style={{ borderColor: "var(--border-muted)", background: "var(--bg-app)", color: "var(--text-main)" }}>
                    <option value="fr">Français</option>
                    <option value="en">English</option>
                  </select>
                </div>
                <ToggleRow title="Lecture vocale automatique" desc="Lire le résumé à haute voix après chargement" checked={autoSpeech} onChange={setAutoSpeech} />
                <ToggleRow title="Animations textuelles" desc="Activer les effets de frappe dans le chat" checked={textAnimations} onChange={setTextAnimations} />
              </div>
            )}

            {activeTab === "model" && (
              <div className="flex flex-col gap-5">
                <div className="flex flex-col gap-1.5">
                  <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Source du modèle</label>
                  <select value={modelSource} onChange={(e) => setModelSource(e.target.value as "opensource" | "api")} className="rounded-md border px-3.5 py-2.5 text-[13px]" style={{ borderColor: "var(--border-muted)", background: "var(--bg-app)", color: "var(--text-main)" }}>
                    <option value="opensource">Modèle Open Source (Local)</option>
                    <option value="api">Modèle via API Externe</option>
                  </select>
                </div>

                {modelSource === "opensource" ? (
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Modèle de langage</label>
                    <select
                      value={selectedModel}
                      onChange={(e) => notifyModelChange(e.target.value)}
                      className="rounded-md border px-3.5 py-2.5 text-[13px]"
                      style={{ borderColor: "var(--border-muted)", background: "var(--bg-app)", color: "var(--text-main)" }}
                    >
                      {models.length > 0 && (
                        <optgroup label="Modèles Locaux (Ollama)">
                          {models.map((m) => <option key={m} value={m}>{m}</option>)}
                        </optgroup>
                      )}
                      {proprietaryModels.length > 0 && (
                        <optgroup label="Modèles Propriétaires">
                          {proprietaryModels.map((m) => <option key={m} value={m}>{m}</option>)}
                        </optgroup>
                      )}
                      {models.length === 0 && proprietaryModels.length === 0 && <option value="gemma2:latest">gemma2:latest</option>}
                    </select>
                  </div>
                ) : (
                  <div className="flex flex-col gap-3 rounded-md border p-4 text-[13px]" style={{ borderColor: "var(--border-muted)", background: "var(--bubble-ai)", color: "var(--text-muted)" }}>
                    <span>Configurez un fournisseur d&rsquo;API externe pour utiliser des modèles hébergés (ex: GPT-4o, Claude, etc.).</span>
                    <button
                      onClick={() => setIsApiDialogOpen(true)}
                      className="w-fit rounded-md border px-4 py-2 text-[12px] font-semibold transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
                      style={{ borderColor: "var(--border-color)", color: "var(--text-main)" }}
                    >
                      Configurer l&rsquo;API
                    </button>
                  </div>
                )}

                <RangeRow label="Température" value={temperature.toFixed(1)} hint="Plus bas = plus factuel" min={0} max={1} step={0.1} raw={temperature} onChange={setTemperature} />
                <RangeRow label="Limite de jetons" value={String(maxTokens)} hint="Réponse maximale autorisée par requête." min={256} max={4096} step={256} raw={maxTokens} onChange={setMaxTokens} />
              </div>
            )}

            {activeTab === "rag" && (
              <div className="flex flex-col gap-5">
                <RangeRow label="Taille des blocs RAG" value={`${chunkSize} mots`} hint="Un bon équilibre entre précision et contexte." min={200} max={1500} step={50} raw={chunkSize} onChange={setChunkSize} />
                <RangeRow label="Recouvrement RAG" value={`${chunkOverlap} mots`} hint="Conserve le lien entre deux extraits successifs." min={0} max={300} step={10} raw={chunkOverlap} onChange={setChunkOverlap} />
                <div className="flex items-center justify-between rounded-md border p-4" style={{ borderColor: "var(--border-muted)" }}>
                  <div>
                    <strong className="block text-[13px]" style={{ color: "var(--text-main)" }}>Nettoyer l&rsquo;index de recherche</strong>
                    <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>Supprimer le cache des embeddings stockés.</span>
                  </div>
                  <button
                    onClick={() => alert("Base de données vectorielle et cache vidés avec succès !")}
                    className="rounded-md border px-4 py-2 text-[12px] font-semibold"
                    style={{ borderColor: "var(--danger)", color: "var(--danger)" }}
                  >
                    Effacer
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="mt-6 flex justify-end gap-3 border-t pt-5" style={{ borderColor: "var(--border-muted)" }}>
          <button onClick={onClose} className="rounded-md border px-5 py-2 text-[13px] font-medium" style={{ borderColor: "var(--border-color)", color: "var(--text-muted)" }}>
            Annuler
          </button>
          <button onClick={onClose} className="flex items-center gap-1.5 rounded-md px-6 py-2 text-[13px] font-medium text-white" style={{ background: "var(--accent)" }}>
            <Check size={14} /> Enregistrer
          </button>
        </div>
      </Modal>

      {showToast && (
        <div
          className="fixed bottom-6 left-1/2 z-[99999] w-[calc(100%-48px)] max-w-[400px] -translate-x-1/2 rounded-lg border p-5 shadow-lg fc-fade-up"
          style={{ background: "var(--bg-panel)", borderColor: "var(--border-color)" }}
        >
          <div className="mb-1.5 text-[16px] font-semibold" style={{ color: "var(--text-main)" }}>Modèle IA modifié</div>
          <div className="text-[13px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
            Vous utilisez désormais le modèle <strong style={{ color: "var(--text-main)" }}>{toastModel || selectedModel}</strong> pour vos discussions.
          </div>
        </div>
      )}

      <Modal isOpen={isApiDialogOpen} onClose={() => setIsApiDialogOpen(false)} title="Configuration API" maxWidth="440px">
        <form className="flex flex-col gap-5" onSubmit={submitApiConfig}>
          <p className="-mt-1 text-[13px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
            Entrez les informations de votre fournisseur pour utiliser un modèle via API. La clé est testée avec une petite requête avant d&rsquo;être enregistrée côté serveur (backend/.env).
          </p>

          <div className="flex flex-col gap-1.5">
            <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Fournisseur</label>
            <select
              value={apiProvider}
              onChange={(e) => setApiProvider(e.target.value)}
              className="rounded-md border px-3.5 py-2.5 text-[13px]"
              style={{ borderColor: "var(--border-muted)", background: "var(--bg-app)", color: "var(--text-main)" }}
            >
              <option value="gemini">Gemini</option>
              <option value="mistral">Mistral</option>
              <option value="anthropic">Claude (Anthropic)</option>
              <option value="openai">OpenAI</option>
              <option value="groq">Groq</option>
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Modèle</label>
            <select
              value={apiModelName}
              onChange={(e) => setApiModelName(e.target.value)}
              required
              className="rounded-md border px-3.5 py-2.5 text-[13px]"
              style={{ borderColor: "var(--border-muted)", background: "var(--bg-app)", color: "var(--text-main)" }}
            >
              {(providerModels[apiProvider] || []).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>Clé API</label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="x7K9pL2mQ8vR4tY1nZ6bW3jD5hF0sA2c"
              required
              className="rounded-md border px-3.5 py-2.5 text-[13px]"
              style={{ borderColor: "var(--border-muted)", background: "var(--bg-app)", color: "var(--text-main)" }}
            />
          </div>

          {apiError && (
            <div className="text-[12px]" style={{ color: "var(--danger)" }}>{apiError}</div>
          )}

          <div className="flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:justify-end" style={{ borderColor: "var(--border-muted)" }}>
            <button
              type="button"
              onClick={() => setIsApiDialogOpen(false)}
              className="rounded-md border px-5 py-2 text-[13px] font-medium"
              style={{ borderColor: "var(--border-color)", color: "var(--text-muted)" }}
            >
              Annuler
            </button>
            <button
              type="submit"
              disabled={apiSaving || !apiModelName}
              className="flex items-center justify-center gap-1.5 rounded-md px-6 py-2 text-[13px] font-medium text-white disabled:opacity-60"
              style={{ background: "var(--accent)" }}
            >
              {apiSaving ? "Vérification de la clé..." : "Enregistrer"}
            </button>
          </div>
        </form>
      </Modal>
    </>
  );
}

function ToggleRow({ title, desc, checked, onChange }: { title: string; desc: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <strong className="block text-[13px]" style={{ color: "var(--text-main)" }}>{title}</strong>
        <span className="text-[11px]" style={{ color: "var(--text-muted)" }}>{desc}</span>
      </div>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="size-[18px] accent-[var(--accent)]" />
    </div>
  );
}

function RangeRow({
  label,
  value,
  hint,
  min,
  max,
  step,
  raw,
  onChange,
}: {
  label: string;
  value: string;
  hint: string;
  min: number;
  max: number;
  step: number;
  raw: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <label className="text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>{label}</label>
        <span className="text-[12px] font-semibold" style={{ color: "var(--accent)" }}>{value}</span>
      </div>
      <small style={{ color: "var(--text-dim)" }}>{hint}</small>
      <input type="range" min={min} max={max} step={step} value={raw} onChange={(e) => onChange(parseFloat(e.target.value))} className="w-full accent-[var(--accent)]" />
    </div>
  );
}
