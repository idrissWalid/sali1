/* eslint-disable react-hooks/set-state-in-effect */
"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Image from "next/image";
import { Moon, Plus, Settings2, Share2, Sun } from "lucide-react";
import { Panel, Group, Separator } from "react-resizable-panels";
import Sidebar from "./components/Sidebar";
import SourcesPanel from "./components/SourcesPanel";
import ChatPanel from "./components/ChatPanel";
import StudioPanel from "./components/StudioPanel";
import SettingsModal from "./components/SettingsModal";
import ModelsModal from "./components/ModelsModal";
import ShareModal from "./components/ShareModal";
import AvatarMenu from "./components/AvatarMenu";
import Modal from "./components/Modal";
import SourceHistoryDock from "./components/SourceHistoryDock";

interface Source {
  name: string;
  type: "tabular" | "document";
  meta: string;
}

interface SessionItem {
  id: string;
  title: string;
  type: string;
  filename?: string;
  created_at: string;
}

interface UploadData {
  session_id: string;
  filename?: string;
  profile?: {
    filename?: string;
  };
  type: string;
  interpretation?: string;
  summary?: string;
}

export default function Home() {
  const [sources, setSources] = useState<Source[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [initialMessage, setInitialMessage] = useState<{ role: "assistant"; text: string; isSummary?: boolean } | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [leftTab, setLeftTab] = useState<"sources" | "history">("sources");
  const [openUpload, setOpenUpload] = useState<(() => void) | null>(null);
  
  const registerUploadHandler = useCallback((handler: (() => void) | null) => {
    setOpenUpload(() => handler);
  }, []);
  
  const [models, setModels] = useState<string[]>(["gemma2:latest"]);
  const [proprietaryModels, setProprietaryModels] = useState<string[]>(["gemini-3.1-flash-lite-preview"]);
  const [selectedModel, setSelectedModel] = useState<string>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("selected_model") || "gemma2:latest";
    }
    return "gemma2:latest";
  });

  // Modal & Dropdown visibility states
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isModelsOpen, setIsModelsOpen] = useState(false);
  const [generatedContent, setGeneratedContent] = useState<string>("");
  const [isShareOpen, setIsShareOpen] = useState(false);
  const [isAvatarOpen, setIsAvatarOpen] = useState(false);
  const [isNewSessionConfirmOpen, setIsNewSessionConfirmOpen] = useState(false);
  const [isPageLoading, setIsPageLoading] = useState(true);

  // Anchor ref for positioning avatar dropdown
  const avatarRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    if (sessionId) {
      localStorage.setItem("active_session_id", sessionId);
    } else {
      localStorage.removeItem("active_session_id");
    }
  }, [sessionId]);

  const fetchSessions = async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/sessions`);
      const data = await res.json();
      setSessions(data || []);
    } catch (err) {
      console.error("Erreur lors du chargement des sessions:", err);
    }
  };

  const fetchModels = async () => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/llm-models`);
      const data = await res.json();
      if (data.models) {
        setModels(data.models);
      }
      if (data.proprietary) {
        setProprietaryModels(data.proprietary);
      }
      const allModels = [...(data.models || []), ...(data.proprietary || [])];
      if (allModels.length > 0) {
        const savedModel = localStorage.getItem("selected_model");
        if (savedModel && allModels.includes(savedModel)) {
          setSelectedModel(savedModel);
        } else {
          setSelectedModel(allModels[0]);
        }
      }
    } catch (err) {
      console.error("Erreur lors du chargement des modèles LLM:", err);
    }
  };


  const handleSelectSession = async (id: string) => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/sessions/${id}`);
      if (!res.ok) throw new Error("Erreur serveur");
      const data = await res.json();
      
      setSessionId(data.id);
      
      // Mettre à jour les sources avec le fichier de la session
      if (data.filename) {
        setSources([
          {
            name: data.filename,
            type: data.type === "tabular" ? "tabular" : "document",
            meta: data.type === "tabular" ? "Données tabulaires" : "Document PDF/Word",
          }
        ]);
        setLeftTab("sources");
      } else {
        setSources([]);
      }
      
      // Pas de message initial lors de la reprise d'une session
      setInitialMessage(null);
    } catch (err) {
      console.error("Erreur lors du chargement des détails de la session:", err);
      if (id === localStorage.getItem("active_session_id")) {
        localStorage.removeItem("active_session_id");
      }
    }
  };

  const handleDeleteSession = async (id: string) => {
    if (!confirm("Voulez-vous vraiment supprimer cette discussion ?")) return;
    
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      await fetch(`${apiUrl}/api/sessions/${id}`, { method: "DELETE" });
      
      // Recharger la liste
      fetchSessions();
      
      // Si la session en cours a été supprimée, on réinitialise
      if (sessionId === id) {
        handleNewSession();
      }
    } catch (err) {
      console.error("Erreur lors de la suppression de la session:", err);
    }
  };

  const handleUpload = (data: UploadData) => {
    setSessionId(data.session_id);
    const newSource: Source = {
      name: data.filename || data.profile?.filename || "Source",
      type: data.type === "tabular_analyzed" ? "tabular" : "document",
      meta: data.type === "tabular_analyzed" ? "Données tabulaires" : "Document PDF/Word",
    };
    setSources(s => [...s, newSource]);
    setLeftTab("sources");
    const text = data.type === "tabular_analyzed" ? (data.interpretation ?? "") : (data.summary ?? "");
    setInitialMessage({ role: "assistant", text, isSummary: data.type === "tabular_analyzed" });
    
    // Rafraîchir l'historique des sessions
    fetchSessions();
  };

  const handleRemove = (index: number) => {
    setSources(s => s.filter((_, i) => i !== index));
  };

  const handleNewSession = () => {
    setSources([]);
    setSessionId(null);
    setInitialMessage(null);
  };

  useEffect(() => {
    let isMounted = true;

    const initializeApp = async () => {
      try {
        await Promise.all([fetchSessions(), fetchModels()]);
        const savedSessionId = localStorage.getItem("active_session_id");
        if (savedSessionId && isMounted) {
          await handleSelectSession(savedSessionId);
        }
      } finally {
        if (isMounted) {
          setIsPageLoading(false);
        }
      }
    };

    initializeApp();

    return () => {
      isMounted = false;
    };
  }, []);

  if (isPageLoading) {
    return (
      <div className="frontend-loading-shell">
        <div className="frontend-loading-header">
          <div className="frontend-loading-block frontend-loading-block--avatar" />
          <div style={{ display: "flex", alignItems: "center", gap: "10px", flex: 1 }}>
            <div className="frontend-loading-block frontend-loading-block--line" style={{ width: "140px" }} />
            <div className="frontend-loading-block frontend-loading-block--line" style={{ width: "92px" }} />
          </div>
          <div style={{ display: "flex", gap: "8px" }}>
            <div className="frontend-loading-block frontend-loading-block--chip" />
            <div className="frontend-loading-block frontend-loading-block--chip" />
            <div className="frontend-loading-block frontend-loading-block--chip" />
          </div>
        </div>

        <div style={{ display: "flex", flex: 1, gap: "10px" }}>
          <div className="frontend-loading-panel" style={{ width: "22%", padding: "16px" }}>
            <div className="frontend-loading-block frontend-loading-block--line" style={{ width: "70%", marginBottom: "14px" }} />
            <div className="frontend-loading-block frontend-loading-block--line" style={{ width: "100%", marginBottom: "10px" }} />
            <div className="frontend-loading-block frontend-loading-block--line" style={{ width: "88%", marginBottom: "10px" }} />
            <div className="frontend-loading-block frontend-loading-block--line" style={{ width: "60%" }} />
          </div>

          <div className="frontend-loading-panel frontend-loading-panel--wide" style={{ flex: 1, padding: "16px" }}>
            <div className="frontend-loading-block frontend-loading-block--line" style={{ width: "34%", marginBottom: "16px" }} />
            <div className="frontend-loading-block frontend-loading-block--card" style={{ height: "120px", marginBottom: "12px" }} />
            <div className="frontend-loading-block frontend-loading-block--card" style={{ height: "70px" }} />
          </div>

          <div className="frontend-loading-panel" style={{ width: "23%", padding: "16px" }}>
            <div className="frontend-loading-block frontend-loading-block--line" style={{ width: "64%", marginBottom: "14px" }} />
            <div className="frontend-loading-block frontend-loading-block--card" style={{ height: "88px" }} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "var(--bg-app)", color: "var(--text-main)", transition: "background-color 0.3s ease, color 0.3s ease", overflow: "hidden" }}>

      {/* TOPBAR */}
      <div style={{
        height: "60px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 20px",
        background: "color-mix(in srgb, var(--bg-panel) 88%, transparent)",
        borderBottom: "1px solid rgba(255,255,255,0.07)",
        backdropFilter: "blur(12px)",
        flexShrink: 0,
        position: "relative",
        zIndex: 10,
      }}>

        {/* Gauche : logo + nom */}
        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <div style={{
            width: "34px", height: "34px",
            borderRadius: "10px",
            overflow: "hidden",
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "linear-gradient(135deg, rgba(138,180,248,0.15), rgba(167,139,250,0.1))",
            border: "1px solid rgba(138,180,248,0.2)",
          }}>
            <Image
              src="/logo.png"
              alt="Logo"
              width={32}
              height={32}
              style={{ objectFit: "contain", width: "auto", height: "auto" }}
            />
          </div>
          <span style={{
            fontFamily: "'Google Sans',sans-serif",
            fontSize: "16px",
            fontWeight: 600,
            color: "var(--text-main)",
            letterSpacing: "-0.02em",
          }}>
            No-Code Data Intelligence
          </span>
        </div>

        {/* Droite : boutons */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          
          {/* Theme Toggle */}
          <button
            onClick={(e) => {
              const x = e.clientX;
              const y = e.clientY;
              const maxRadius = Math.hypot(
                Math.max(x, window.innerWidth - x),
                Math.max(y, window.innerHeight - y)
              );
              
              document.documentElement.style.setProperty('--click-x', `${x}px`);
              document.documentElement.style.setProperty('--click-y', `${y}px`);
              document.documentElement.style.setProperty('--max-radius', `${maxRadius}px`);

              const newTheme = theme === "dark" ? "light" : "dark";

              if (!document.startViewTransition) {
                setTheme(newTheme);
                return;
              }

              document.startViewTransition(() => {
                document.documentElement.setAttribute("data-theme", newTheme);
                setTheme(newTheme);
              });
            }}
            style={{
              width: "34px", height: "34px",
              borderRadius: "50%",
              border: "1px solid var(--border-color)",
              background: "transparent",
              color: "var(--text-muted)",
              cursor: "pointer",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: "16px",
              transition: "background 0.2s, color 0.2s, transform 0.2s",
            }}
            onMouseEnter={e => { e.currentTarget.style.background = "var(--bubble-ai)"; e.currentTarget.style.transform = "rotate(20deg) scale(1.05)"; }}
            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.transform = "none"; }}
          >
            {theme === "dark" ? <Sun size={17} strokeWidth={1.8} /> : <Moon size={17} strokeWidth={1.8} />}
          </button>

          <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
            {[
              { label: "Nouvelle session", icon: Plus, action: () => {
                  if (sources.length > 0) {
                    setIsNewSessionConfirmOpen(true);
                  } else {
                    handleNewSession();
                  }
                }
              },
              { label: "Partager", icon: Share2, action: () => setIsShareOpen(true) },
              { label: "Paramètres", icon: Settings2, action: () => setIsSettingsOpen(true) },
            ].map((btn, i) => (
              <button key={i} onClick={btn.action}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "7px 16px",
                  borderRadius: "20px",
                  border: "1px solid var(--border-color)",
                  color: "var(--text-muted)",
                  fontSize: "13px",
                  fontFamily: "'Google Sans',sans-serif",
                  background: "transparent",
                  cursor: "pointer",
                  transition: "background 0.15s, color 0.15s, border-color 0.15s, transform 0.12s",
                  fontWeight: 500,
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.background = "var(--bubble-ai)";
                  e.currentTarget.style.color = "var(--text-main)";
                  e.currentTarget.style.borderColor = "rgba(255,255,255,0.14)";
                  e.currentTarget.style.transform = "translateY(-1px)";
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = "transparent";
                  e.currentTarget.style.color = "var(--text-muted)";
                  e.currentTarget.style.borderColor = "var(--border-color)";
                  e.currentTarget.style.transform = "none";
                }}
              >
                <btn.icon size={15} strokeWidth={1.8} />
                {btn.label}
              </button>
            ))}
            <div
              ref={avatarRef}
              onClick={() => setIsAvatarOpen(!isAvatarOpen)}
              style={{
                width: "34px", height: "34px",
                borderRadius: "50%",
                background: "linear-gradient(135deg,#8ab4f8,#a78bfa)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: "13px", fontWeight: 600, color: "#fff",
                cursor: "pointer",
                boxShadow: "0 2px 10px rgba(138,180,248,0.3)",
                transition: "transform 0.15s, box-shadow 0.15s",
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLElement).style.transform = "scale(1.08)";
                (e.currentTarget as HTMLElement).style.boxShadow = "0 4px 16px rgba(138,180,248,0.45)";
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLElement).style.transform = "none";
                (e.currentTarget as HTMLElement).style.boxShadow = "0 2px 10px rgba(138,180,248,0.3)";
              }}
            >
              W
            </div>
          </div>

          {/* Avatar Menu Dropdown Overlay */}
          <AvatarMenu isOpen={isAvatarOpen} onClose={() => setIsAvatarOpen(false)} anchorRef={avatarRef} />
        </div>

      </div>

      {/* MAIN */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden", padding: "10px 8px 0 8px" }}>
        <Group orientation="horizontal" style={{ width: "100%", height: "100%" }}>
          <Panel defaultSize={22} minSize={15} style={{ height: "100%" }}>
            <div style={{
              height: "100%",
              display: "flex",
              flexDirection: "column",
              background: "var(--bg-panel)",
              borderRadius: "12px",
              border: "1px solid var(--border-color)",
              overflow: "hidden",
            }}>


              {/* Tab Content */}
              <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
                <div style={{ display: leftTab === "sources" ? "flex" : "none", height: "100%", flexDirection: "column" }}>
                  <SourcesPanel
                    sources={sources}
                    onUpload={handleUpload}
                    onRemove={handleRemove}
                    hideHeader={true}
                    selectedModel={selectedModel}
                    registerUploadHandler={registerUploadHandler}
                  />
                </div>
                <div style={{ display: leftTab === "history" ? "flex" : "none", height: "100%", flexDirection: "column" }}>
                  <Sidebar
                    sessions={sessions}
                    currentSessionId={sessionId}
                    onSelectSession={handleSelectSession}
                    onDeleteSession={handleDeleteSession}
                    onNewSession={handleNewSession}
                    hideHeader={true}
                  />
                </div>
              </div>

              <div className="source-history-dock-wrap">
                <SourceHistoryDock
                  activeTab={leftTab}
                  sourceCount={sources.length}
                  onTabChange={setLeftTab}
                />
              </div>
            </div>
          </Panel>
          <Separator style={{ width: "8px", background: "transparent", cursor: "col-resize", transition: "background 0.2s" }} />
          <Panel defaultSize={55} minSize={30} style={{ height: "100%" }}>
            <ChatPanel
              sessionId={sessionId}
              sourceCount={sources.length}
              initialMessage={initialMessage}
              selectedModel={selectedModel}
              onUploadClick={() => openUpload?.()}
              onAssistantMessage={(text) => setGeneratedContent(text)}
            />
          </Panel>
          <Separator style={{ width: "8px", background: "transparent", cursor: "col-resize", transition: "background 0.2s" }} />
          <Panel defaultSize={23} minSize={15} style={{ height: "100%" }}>
            <StudioPanel sessionId={sessionId} generatedContent={generatedContent} openModels={() => setIsModelsOpen(true)} />
          </Panel>
        </Group>
      </div>

      {/* FOOTER */}
      <div style={{ height: "28px", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, fontSize: "11px", color: "var(--text-dim)" }}>
        No-Code Data Intelligence peut se tromper. Veuillez donc vérifier ses réponses.
      </div>

      {/* Global Modals */}
      <SettingsModal 
        isOpen={isSettingsOpen} 
        onClose={() => setIsSettingsOpen(false)} 
        models={models}
        proprietaryModels={proprietaryModels}
        selectedModel={selectedModel}
        onModelChange={(m) => {
          setSelectedModel(m);
          localStorage.setItem("selected_model", m);
        }}
      />
      <ModelsModal isOpen={isModelsOpen} onClose={() => setIsModelsOpen(false)} sessionId={sessionId} />
      <ShareModal isOpen={isShareOpen} onClose={() => setIsShareOpen(false)} sourcesCount={sources.length} />

      {/* Confirmation Modal for Reset Session */}
      <Modal isOpen={isNewSessionConfirmOpen} onClose={() => setIsNewSessionConfirmOpen(false)} title="Confirmation">
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <div style={{ fontSize: "14px", color: "var(--text-main)" }}>
            {"Êtes-vous sûr de vouloir commencer une nouvelle session ? Toutes vos sources et discussions en cours seront définitivement effacées de l'écran."}
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", gap: "12px", marginTop: "8px" }}>
            <button
              onClick={() => setIsNewSessionConfirmOpen(false)}
              style={{
                padding: "8px 18px",
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
                handleNewSession();
                setIsNewSessionConfirmOpen(false);
              }}
              style={{
                padding: "8px 24px",
                borderRadius: "18px",
                border: "none",
                color: "var(--bg-app)",
                background: "#ea4335",
                fontSize: "13px",
                fontWeight: 500,
                cursor: "pointer",
              }}
            >
              Confirmer
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
