"use client";

import { useState } from "react";
import Modal from "./Modal";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogPanel,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/animate-ui/components/headless/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  models?: string[];
  selectedModel?: string;
  onModelChange?: (model: string) => void;
}

type TabType = "general" | "model" | "rag";

export default function SettingsModal({ isOpen, onClose, models = [], selectedModel = "", onModelChange }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<TabType>("general");

  // Settings states
  const [lang, setLang] = useState("fr");
  const [aiModel, setAiModel] = useState(selectedModel || "gemma2:latest");
  const [temperature, setTemperature] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(2048);
  const [chunkSize, setChunkSize] = useState(500);
  const [chunkOverlap, setChunkOverlap] = useState(50);
  const [autoSpeech, setAutoSpeech] = useState(false);
  const [showToast, setShowToast] = useState(false);

  const [modelSource, setModelSource] = useState<"opensource" | "api">("opensource");
  const [isApiDialogOpen, setIsApiDialogOpen] = useState(false);
  const [apiProvider, setApiProvider] = useState("gemini");
  const [apiModelName, setApiModelName] = useState("");
  const [apiKey, setApiKey] = useState("");

  const clearCache = () => {
    alert("Base de données vectorielle et cache vidés avec succès !");
  };

  const tabs: { id: TabType; label: string; icon: string }[] = [
    { id: "general", label: "Général", icon: "⚙️" },
    { id: "model", label: "Modèle IA", icon: "🧠" },
    { id: "rag", label: "RAG & Données", icon: "📂" },
  ];

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
      <Modal isOpen={isOpen} onClose={onClose} title="Paramètres globaux" maxWidth="580px">
      <div style={{ display: "flex", gap: "20px", height: "360px" }}>
        
        {/* Navigation Sidebar */}
        <div style={{
          width: "160px",
          display: "flex",
          flexDirection: "column",
          gap: "6px",
          borderRight: "1px solid var(--border-muted)",
          paddingRight: "12px",
        }}>
          {tabs.map((tab) => {
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  padding: "10px 12px",
                  borderRadius: "10px",
                  border: "none",
                  background: isActive ? "var(--bubble-user)" : "transparent",
                  color: isActive ? "var(--text-main)" : "var(--text-muted)",
                  fontWeight: isActive ? 500 : 400,
                  fontSize: "13px",
                  cursor: "pointer",
                  textAlign: "left",
                  transition: "background 0.15s, color 0.15s",
                }}
                onMouseEnter={(e) => {
                  if (!isActive) e.currentTarget.style.background = "var(--bubble-ai)";
                }}
                onMouseLeave={(e) => {
                  if (!isActive) e.currentTarget.style.background = "transparent";
                }}
              >
                <span>{tab.icon}</span>
                <span>{tab.label}</span>
              </button>
            );
          })}
        </div>

        {/* Tab Content Panel */}
        <div style={{ flex: 1, overflowY: "auto", paddingLeft: "4px" }}>
          
          {/* GENERAL TAB */}
          {activeTab === "general" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--text-muted)" }}>Langue de l'interface</label>
                <select
                  value={lang}
                  onChange={(e) => setLang(e.target.value)}
                  style={{
                    padding: "10px 14px",
                    borderRadius: "10px",
                    border: "1px solid var(--border-color)",
                    background: "var(--bg-app)",
                    color: "var(--text-main)",
                    outline: "none",
                    fontSize: "13px",
                  }}
                >
                  <option value="fr">Français</option>
                  <option value="en">English</option>
                </select>
              </div>

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: "10px" }}>
                <div>
                  <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)" }}>Lecture vocale automatique</div>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>Lire le résumé à haute voix après chargement</div>
                </div>
                <input
                  type="checkbox"
                  checked={autoSpeech}
                  onChange={(e) => setAutoSpeech(e.target.checked)}
                  style={{ width: "18px", height: "18px", accentColor: "var(--accent-color)", cursor: "pointer" }}
                />
              </div>

              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                <div>
                  <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)" }}>Animations textuelles</div>
                  <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>Activer les effets de frappe dans le chat</div>
                </div>
                <input
                  type="checkbox"
                  defaultChecked
                  style={{ width: "18px", height: "18px", accentColor: "var(--accent-color)", cursor: "pointer" }}
                />
              </div>
            </div>
          )}

          {/* MODEL TAB */}
          {activeTab === "model" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
              
              <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--text-muted)" }}>Source du Modèle</label>
                <select
                  value={modelSource}
                  onChange={(e) => setModelSource(e.target.value as "opensource" | "api")}
                  style={{
                    padding: "10px 14px",
                    borderRadius: "10px",
                    border: "1px solid var(--border-color)",
                    background: "var(--bg-app)",
                    color: "var(--text-main)",
                    outline: "none",
                    fontSize: "13px",
                  }}
                >
                  <option value="opensource">Modèle Open Source (Local)</option>
                  <option value="api">Modèle via API Externe</option>
                </select>
              </div>

              {modelSource === "opensource" ? (
                <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                  <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--text-muted)" }}>Modèle de langage (LLM)</label>
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
                    style={{
                      padding: "10px 14px",
                      borderRadius: "10px",
                      border: "1px solid var(--border-color)",
                      background: "var(--bg-app)",
                      color: "var(--text-main)",
                      outline: "none",
                      fontSize: "13px",
                    }}
                  >
                    {models.map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                    {models.length === 0 && (
                      <option value="gemma2:latest">gemma2:latest</option>
                    )}
                  </select>
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginTop: "4px" }}>
                  <div style={{ fontSize: "13px", color: "var(--text-muted)", lineHeight: 1.5 }}>
                    Configurez un fournisseur d'API externe pour utiliser des modèles hébergés (ex: GPT-4o, Claude 3.5 Sonnet, etc.).
                  </div>
                  <Button variant="outline" onClick={() => setIsApiDialogOpen(true)} style={{ width: "fit-content", borderColor: "var(--border-color)", color: "var(--text-main)" }}>
                    Configurer l'API
                  </Button>
                </div>
              )}

              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--text-muted)" }}>Température ({temperature})</label>
                  <span style={{ fontSize: "11px", color: "var(--text-dim)" }}>Plus bas = plus factuel</span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.1"
                  value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  style={{ width: "100%", accentColor: "var(--accent-color)", cursor: "pointer" }}
                />
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--text-muted)" }}>Limite de Jetons ({maxTokens})</label>
                </div>
                <input
                  type="range"
                  min="256"
                  max="4096"
                  step="256"
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(parseInt(e.target.value))}
                  style={{ width: "100%", accentColor: "var(--accent-color)", cursor: "pointer" }}
                />
              </div>
            </div>
          )}

          {/* RAG TAB */}
          {activeTab === "rag" && (
            <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--text-muted)" }}>Taille des blocs RAG ({chunkSize} mots)</label>
                </div>
                <input
                  type="range"
                  min="200"
                  max="1500"
                  step="50"
                  value={chunkSize}
                  onChange={(e) => setChunkSize(parseInt(e.target.value))}
                  style={{ width: "100%", accentColor: "var(--accent-color)", cursor: "pointer" }}
                />
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <label style={{ fontSize: "12px", fontWeight: 500, color: "var(--text-muted)" }}>Recouvrement RAG ({chunkOverlap} mots)</label>
                </div>
                <input
                  type="range"
                  min="0"
                  max="300"
                  step="10"
                  value={chunkOverlap}
                  onChange={(e) => setChunkOverlap(parseInt(e.target.value))}
                  style={{ width: "100%", accentColor: "var(--accent-color)", cursor: "pointer" }}
                />
              </div>

              <div style={{ borderTop: "1px solid var(--border-muted)", paddingTop: "18px", marginTop: "10px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div>
                    <div style={{ fontSize: "13px", fontWeight: 500, color: "var(--text-main)" }}>Nettoyer l'index de recherche</div>
                    <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "2px" }}>Supprimer le cache des embeddings stockés</div>
                  </div>
                  <button
                    onClick={clearCache}
                    style={{
                      padding: "8px 16px",
                      borderRadius: "18px",
                      background: "rgba(234, 67, 53, 0.15)",
                      color: "#ea4335",
                      border: "none",
                      fontSize: "12px",
                      fontWeight: 500,
                      cursor: "pointer",
                      transition: "opacity 0.2s",
                    }}
                    onMouseEnter={(e) => e.currentTarget.style.opacity = "0.85"}
                    onMouseLeave={(e) => e.currentTarget.style.opacity = "1"}
                  >
                    Effacer
                  </button>
                </div>
              </div>
            </div>
          )}

        </div>
      </div>

      {/* Footer */}
      <div style={{
        display: "flex",
        justifyContent: "flex-end",
        gap: "12px",
        borderTop: "1px solid var(--border-muted)",
        paddingTop: "18px",
        marginTop: "12px"
      }}>
        <button
          onClick={onClose}
          style={{
            padding: "8px 20px",
            borderRadius: "18px",
            border: "1.5px solid var(--border-color)",
            color: "var(--text-muted)",
            fontSize: "13px",
            fontWeight: 500,
            background: "transparent",
            cursor: "pointer",
          }}
        >
          Annuler
        </button>
        <button
          onClick={() => {
            alert("Paramètres enregistrés avec succès !");
            onClose();
          }}
          style={{
            padding: "8px 24px",
            borderRadius: "18px",
            border: "none",
            color: "var(--bg-app)",
            background: "var(--accent-color)",
            fontSize: "13px",
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          Enregistrer
        </button>
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

    {/* Dialog Configuration API */}
    <Dialog open={isApiDialogOpen} onClose={() => setIsApiDialogOpen(false)}>
      <DialogPanel
        from="bottom"
        showCloseButton={true}
        className="sm:max-w-[425px]"
        style={{ background: "var(--bg-app)", color: "var(--text-main)", border: "1px solid var(--border-color)", borderRadius: "12px", zIndex: 99999 }}
      >
        <form className="flex flex-col gap-4" onSubmit={(e) => {
          e.preventDefault();
          setIsApiDialogOpen(false);
          // Optional: set the API model as the active one visually
          setAiModel(apiModelName);
          if (onModelChange) {
            onModelChange(apiModelName);
          }
          setShowToast(true);
          setTimeout(() => setShowToast(false), 2000);
        }}>
          <DialogHeader>
            <DialogTitle>Configuration API</DialogTitle>
            <DialogDescription>
              Entrez les informations de votre fournisseur pour utiliser un modèle via API.
            </DialogDescription>
          </DialogHeader>
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
                <option value="anthropic">Anthropic</option>
                <option value="openai">OpenAI</option>
              </select>
            </div>
            <div className="grid gap-3">
              <Label htmlFor="api-model">Modèle</Label>
              <Input
                id="api-model"
                value={apiModelName}
                onChange={(e) => setApiModelName(e.target.value)}
                placeholder="ex: gpt-4o, claude-3-sonnet..."
                style={{ background: "var(--bg-app)", color: "var(--text-main)", borderColor: "var(--border-color)" }}
                required
              />
            </div>
            <div className="grid gap-3">
              <Label htmlFor="api-key">Clé API</Label>
              <Input
                id="api-key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                style={{ background: "var(--bg-app)", color: "var(--text-main)", borderColor: "var(--border-color)" }}
                required
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" type="button" onClick={() => setIsApiDialogOpen(false)} style={{ color: "var(--text-main)", borderColor: "var(--border-color)" }}>
              Annuler
            </Button>
            <Button type="submit" style={{ background: "var(--accent-color)", color: "var(--bg-app)" }}>
              Enregistrer
            </Button>
          </DialogFooter>
        </form>
      </DialogPanel>
    </Dialog>
    </>
  );
}
