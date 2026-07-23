"use client";

import { useEffect, useState } from "react";
import Modal from "./Modal";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import StatefulSaveButton from "./StatefulSaveButton";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  models?: string[];
  proprietaryModels?: string[];
  selectedModel?: string;
  onModelChange?: (model: string) => void;
  onModelsRefetch?: () => void;
}

type TabType = "general" | "model" | "rag";

export default function SettingsModal({
  isOpen,
  onClose,
  models = [],
  proprietaryModels = [],
  selectedModel = "",
  onModelChange,
  onModelsRefetch,
}: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<TabType>("general");

  // Settings states
  const [lang, setLang] = useState("fr");
  const [aiModel, setAiModel] = useState(selectedModel || "gemma2:latest");
  const [temperature, setTemperature] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(2048);
  const [chunkSize, setChunkSize] = useState(500);
  const [chunkOverlap, setChunkOverlap] = useState(50);
  const [autoSpeech, setAutoSpeech] = useState(false);
  const [textAnimations, setTextAnimations] = useState(true);
  const [showToast, setShowToast] = useState(false);

  const [modelSource, setModelSource] = useState<"opensource" | "api">("opensource");
  const [isApiDialogOpen, setIsApiDialogOpen] = useState(false);
  const [apiProvider, setApiProvider] = useState("gemini");
  const [apiModelName, setApiModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiSaving, setApiSaving] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [providerModels, setProviderModels] = useState<Record<string, string[]>>({});

  // Charge la liste des fournisseurs et de leurs modèles disponibles dès
  // l'ouverture de la boîte de dialogue "Configuration API".
  useEffect(() => {
    if (!isApiDialogOpen) return;
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    fetch(`${apiUrl}/api/settings/providers`)
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

  const clearCache = () => {
    alert("Base de données vectorielle et cache vidés avec succès !");
  };

  const tabs: { id: TabType; label: string; description: string }[] = [
    { id: "general", label: "Général", description: "Expérience" },
    { id: "model", label: "Modèle IA", description: "Intelligence" },
    { id: "rag", label: "RAG & Données", description: "Indexation" },
  ];

  const tabIcon = (tab: TabType) => {
    if (tab === "general") return <svg viewBox="0 0 24 24" fill="none"><path d="M12 15.25a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5Z" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06-2.1 2.1-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51v.09h-3v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06-2.1-2.1.06-.06A1.65 1.65 0 0 0 7.22 15a1.65 1.65 0 0 0-1.51-1H5.6v-3h.11a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06 2.1-2.1.06.06a1.65 1.65 0 0 0 1.82.33 1.65 1.65 0 0 0 1-1.51V4.8h3v.1a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06 2.1 2.1-.06.06A1.65 1.65 0 0 0 19.4 10a1.65 1.65 0 0 0 1.51 1H21v3h-.09a1.65 1.65 0 0 0-1.51 1Z" /></svg>;
    if (tab === "model") return <svg viewBox="0 0 24 24" fill="none"><path d="M12 3.75c-4.28 0-7.75 2.97-7.75 6.63 0 2.17 1.22 4.1 3.1 5.3v3.57l3.16-1.82c.49.08.99.12 1.49.12 4.28 0 7.75-2.97 7.75-6.63S16.28 3.75 12 3.75Z" /><path d="M9 10.7h.01M12 10.7h.01M15 10.7h.01" strokeLinecap="round" strokeWidth="2.5" /></svg>;
    return <svg viewBox="0 0 24 24" fill="none"><path d="M4 19.25V6.5A2.5 2.5 0 0 1 6.5 4H17.5A2.5 2.5 0 0 1 20 6.5v12.75" /><path d="M2.75 19.25h18.5M8.25 8.25h7.5M8.25 11.5h7.5" strokeLinecap="round" /></svg>;
  };

  return (
    <>
      <style>{`
        @keyframes fadeUpOut {
          0% { opacity: 0; transform: translate(-50%, 20px) scale(0.95); }
          15% { opacity: 1; transform: translate(-50%, 0) scale(1); }
          85% { opacity: 1; transform: translate(-50%, 0) scale(1); }
          100% { opacity: 0; transform: translate(-50%, 20px) scale(0.95); }
        }
      `}</style>
      <Modal isOpen={isOpen} onClose={onClose} title="Préférences" maxWidth="840px">
      <div className="settings-intro">
        <span className="settings-intro__eyebrow">ESPACE DE TRAVAIL</span>
        <p>Personnalisez votre environnement d’analyse sans ajouter de complexité.</p>
      </div>
      <div className="settings-layout">
        <nav className="settings-nav" aria-label="Sections des préférences">
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`settings-nav__item${isActive ? " settings-nav__item--active" : ""}`}
              >
                <span className="settings-nav__icon">{tabIcon(tab.id)}</span>
                <span><strong>{tab.label}</strong><small>{tab.description}</small></span>
              </button>
            );
          })}
        </nav>

        <div className="settings-content">
          
          {/* GENERAL TAB */}
          {activeTab === "general" && (
            <div className="settings-section">
              <div className="settings-section__heading"><h3>Interface</h3><p>Les réglages de votre espace de travail.</p></div>
              <div className="settings-field">
                <label>Langue de l’interface</label>
                <select
                  value={lang}
                  onChange={(e) => setLang(e.target.value)}
                  className="settings-select"
                >
                  <option value="fr">Français</option>
                  <option value="en">English</option>
                </select>
              </div>

              <div className="settings-toggle-row">
                <div><strong>Lecture vocale automatique</strong><span>Lire le résumé à haute voix après chargement</span></div>
                <input
                  type="checkbox"
                  checked={autoSpeech}
                  onChange={(e) => setAutoSpeech(e.target.checked)}
                  className="settings-switch"
                />
              </div>

              <div className="settings-toggle-row">
                <div><strong>Animations textuelles</strong><span>Activer les effets de frappe dans le chat</span></div>
                <input
                  type="checkbox"
                  checked={textAnimations}
                  onChange={(e) => setTextAnimations(e.target.checked)}
                  className="settings-switch"
                />
              </div>
            </div>
          )}

          {/* MODEL TAB */}
          {activeTab === "model" && (
            <div className="settings-section">
              <div className="settings-section__heading"><h3>Modèle de langage</h3><p>Choisissez la source et le comportement de l’assistant.</p></div>
              
              <div className="settings-field">
                <label>Source du modèle</label>
                <select
                  value={modelSource}
                  onChange={(e) => setModelSource(e.target.value as "opensource" | "api")}
                  className="settings-select"
                >
                  <option value="opensource">Modèle Open Source (Local)</option>
                  <option value="api">Modèle via API Externe</option>
                </select>
              </div>

              {modelSource === "opensource" ? (
                <div className="settings-field">
                  <label>Modèle de langage</label>
                  <select
                    value={selectedModel || aiModel}
                    onChange={(e) => {
                      const val = e.target.value;
                      setAiModel(val);
                      if (onModelChange) {
                        onModelChange(val);
                      }
                      setShowToast(true);
                      setTimeout(() => setShowToast(false), 2000);
                    }}
                    className="settings-select"
                  >
                    {models.length > 0 && (
                      <optgroup label="Modèles Locaux (Ollama)">
                        {models.map(m => (
                          <option key={m} value={m}>{m}</option>
                        ))}
                      </optgroup>
                    )}
                    {proprietaryModels.length > 0 && (
                      <optgroup label="Modèles Propriétaires">
                        {proprietaryModels.map(m => (
                          <option key={m} value={m}>{m}</option>
                        ))}
                      </optgroup>
                    )}
                    {models.length === 0 && proprietaryModels.length === 0 && (
                      <option value="gemma2:latest">gemma2:latest</option>
                    )}
                  </select>
                </div>
              ) : (
                <div className="settings-api-card">
                  <div>
                    {"Configurez un fournisseur d'API externe pour utiliser des modèles hébergés (ex: GPT-4o, Claude 3.5 Sonnet, etc.)."}
                  </div>
                  <Button variant="outline" onClick={() => setIsApiDialogOpen(true)} className="settings-secondary-button">
                    {"Configurer l'API"}
                  </Button>
                </div>
              )}

              <div className="settings-range">
                <div><label>Température</label><span>{temperature.toFixed(1)}</span></div>
                <small>Plus bas = plus factuel</small>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  className="settings-range__input"
                />
              </div>

              <div className="settings-range">
                <div><label>Limite de jetons</label><span>{maxTokens}</span></div>
                <small>Réponse maximale autorisée par requête.</small>
                <input
                  type="range"
                  min="256"
                  max="4096"
                  step="256"
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(parseInt(e.target.value))}
                  className="settings-range__input"
                />
              </div>
            </div>
          )}

          {/* RAG TAB */}
          {activeTab === "rag" && (
            <div className="settings-section">
              <div className="settings-section__heading"><h3>Contexte & indexation</h3><p>Réglez la façon dont vos documents sont découpés.</p></div>
              <div className="settings-range">
                <div><label>Taille des blocs RAG</label><span>{chunkSize} mots</span></div>
                <small>Un bon équilibre entre précision et contexte.</small>
                <input
                  type="range"
                  min="200"
                  max="1500"
                  step="50"
                  value={chunkSize}
                  onChange={(e) => setChunkSize(parseInt(e.target.value))}
                  className="settings-range__input"
                />
              </div>

              <div className="settings-range">
                <div><label>Recouvrement RAG</label><span>{chunkOverlap} mots</span></div>
                <small>Conserve le lien entre deux extraits successifs.</small>
                <input
                  type="range"
                  min="0"
                  max="300"
                  step="10"
                  value={chunkOverlap}
                  onChange={(e) => setChunkOverlap(parseInt(e.target.value))}
                  className="settings-range__input"
                />
              </div>

              <div className="settings-danger-zone">
                <div><strong>Nettoyer l’index de recherche</strong><span>Supprimer le cache des embeddings stockés.</span></div>
                  <button
                    onClick={clearCache}
                    className="settings-danger-button"
                  >
                    Effacer
                  </button>
                </div>
            </div>
          )}

        </div>
      </div>

      {/* Footer */}
      <div className="settings-footer">
        <button
          onClick={onClose}
          className="settings-cancel-button"
        >
          Annuler
        </button>
        <StatefulSaveButton
          onSave={() => new Promise<void>((resolve) => {
            setTimeout(() => {
              resolve();
              setTimeout(onClose, 800);
            }, 450);
          })}
        />
      </div>
    </Modal>

    {/* Toast styled as the requested Radix Alert Dialog that disappears after 2s */}
    {showToast && (
      <div style={{
        position: "fixed",
        bottom: "24px",
        left: "50%",
        background: "var(--bg-app)",
        border: "1px solid var(--border-color)",
        padding: "24px",
        borderRadius: "12px",
        boxShadow: "0 10px 40px rgba(0,0,0,0.2)",
        animation: "fadeUpOut 2s ease-in-out forwards",
        zIndex: 99999,
        color: "var(--text-main)",
        width: "calc(100% - 48px)",
        maxWidth: "425px",
        pointerEvents: "none"
      }}>
        <div style={{ fontSize: "18px", fontWeight: 600, marginBottom: "8px" }}>
          Modèle IA modifié
        </div>
        <div style={{ fontSize: "14px", color: "var(--text-muted)", lineHeight: 1.5 }}>
          Vous utilisez désormais le modèle <strong>{modelSource === "api" ? apiModelName || "API externe" : selectedModel || aiModel}</strong> pour vos discussions.
        </div>
      </div>
    )}

    <Modal isOpen={isApiDialogOpen} onClose={() => setIsApiDialogOpen(false)} title="Configuration API" maxWidth="440px">
        <form className="flex flex-col gap-5" onSubmit={async (e) => {
          e.preventDefault();
          setApiError(null);
          setApiSaving(true);
          try {
            const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
            const res = await fetch(`${apiUrl}/api/settings/api-key`, {
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
            setAiModel(composedModel);
            if (onModelChange) {
              onModelChange(composedModel);
            }
            if (onModelsRefetch) {
              onModelsRefetch();
            }

            setApiKey("");
            setIsApiDialogOpen(false);
            setShowToast(true);
            setTimeout(() => setShowToast(false), 2000);
          } catch (err) {
            setApiError(err instanceof Error ? err.message : "Erreur inconnue.");
          } finally {
            setApiSaving(false);
          }
        }}>
          <p className="-mt-2 text-sm leading-6 text-[var(--text-muted)]">
            Entrez les informations de votre fournisseur pour utiliser un modèle via API. La clé est testée avec une petite requête avant d’être enregistrée côté serveur (backend/.env).
          </p>
          <div className="grid gap-4">
            <div className="grid gap-3">
              <Label htmlFor="api-provider">Fournisseur</Label>
              <select
                id="api-provider"
                value={apiProvider}
                onChange={(e) => setApiProvider(e.target.value)}
                style={{
                  padding: "8px 12px",
                  borderRadius: "6px",
                  border: "1px solid var(--border-color)",
                  background: "var(--bg-app)",
                  color: "var(--text-main)",
                  outline: "none",
                  fontSize: "13px",
                }}
              >
                <option value="gemini">Gemini</option>
                <option value="mistral">Mistral</option>
                <option value="anthropic">Claude (Anthropic)</option>
                <option value="openai">OpenAI</option>
                <option value="groq">Groq</option>
              </select>
            </div>
            <div className="grid gap-3">
              <Label htmlFor="api-model">Modèle</Label>
              <select
                id="api-model"
                value={apiModelName}
                onChange={(e) => setApiModelName(e.target.value)}
                required
                style={{
                  padding: "8px 12px",
                  borderRadius: "6px",
                  border: "1px solid var(--border-color)",
                  background: "var(--bg-app)",
                  color: "var(--text-main)",
                  outline: "none",
                  fontSize: "13px",
                }}
              >
                {(providerModels[apiProvider] || []).map((m) => (
                  <option key={m} value={m}>{m}</option>
                ))}
              </select>
            </div>
            <div className="grid gap-3">
              <Label htmlFor="api-key">Clé API</Label>
              <Input
                id="api-key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="x7K9pL2mQ8vR4tY1nZ6bW3jD5hF0sA2c"
                style={{ background: "var(--bg-app)", color: "var(--text-main)", borderColor: "var(--border-color)" }}
                required
              />
            </div>
            {apiError && (
              <div style={{ color: "#ea4335", fontSize: "12px" }}>{apiError}</div>
            )}
          </div>
          <div className="flex flex-col-reverse gap-2 border-t border-[var(--border-muted)] pt-4 sm:flex-row sm:justify-end">
            <Button variant="outline" type="button" onClick={() => setIsApiDialogOpen(false)} style={{ color: "var(--text-main)", borderColor: "var(--border-color)" }}>
              Annuler
            </Button>
            <Button type="submit" disabled={apiSaving || !apiModelName} style={{ background: "var(--accent-color)", color: "var(--bg-app)" }}>
              {apiSaving ? "Vérification de la clé..." : "Enregistrer"}
            </Button>
          </div>
        </form>
    </Modal>
    </>
  );
}
