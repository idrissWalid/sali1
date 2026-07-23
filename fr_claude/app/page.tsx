"use client";

import { Group, Panel, Separator } from "react-resizable-panels";
import { Moon, Plus, Settings2, Share2, Sun } from "lucide-react";
import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import AvatarMenu from "./components/AvatarMenu";
import ChatPanel from "./components/ChatPanel";
import HistoryPanel from "./components/HistoryPanel";
import Modal from "./components/Modal";
import ModelsModal from "./components/ModelsModal";
import SettingsModal from "./components/SettingsModal";
import ShareModal from "./components/ShareModal";
import SideDock from "./components/SideDock";
import SourcesPanel from "./components/SourcesPanel";
import StudioPanel from "./components/StudioPanel";
import { deleteSession, getSession, listLlmModels, listSessions, renameSession } from "./lib/api";
import type { Message, SessionItem, SourceItem, UploadData, UploadProgressState } from "./lib/types";

export default function Home() {
  const [sources, setSources] = useState<SourceItem[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [initialMessage, setInitialMessage] = useState<Message | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">("light");
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [leftTab, setLeftTab] = useState<"sources" | "history">("sources");
  const [openUpload, setOpenUpload] = useState<(() => void) | null>(null);
  const [uploadProgress, setUploadProgress] = useState<UploadProgressState | null>(null);

  const registerUploadHandler = useCallback((handler: (() => void) | null) => {
    setOpenUpload(() => handler);
  }, []);

  const [models, setModels] = useState<string[]>(["gemma2:latest"]);
  const [proprietaryModels, setProprietaryModels] = useState<string[]>(["gemini-3.1-flash-lite-preview"]);
  const [selectedModel, setSelectedModel] = useState("gemma2:latest");

  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isModelsOpen, setIsModelsOpen] = useState(false);
  const [isShareOpen, setIsShareOpen] = useState(false);
  const [isAvatarOpen, setIsAvatarOpen] = useState(false);
  const [isNewSessionConfirmOpen, setIsNewSessionConfirmOpen] = useState(false);
  const [isPageLoading, setIsPageLoading] = useState(true);
  const [generatedContent, setGeneratedContent] = useState("");

  const avatarRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  useEffect(() => {
    // Tant que la restauration initiale (lecture de active_session_id) n'est
    // pas terminée, sessionId vaut encore null : ne pas effacer la valeur
    // persistée sous peine de perdre la session avant même de l'avoir relue
    // (cas typique : retour depuis /dashboard, qui remonte ce composant).
    if (isPageLoading) return;

    if (sessionId) localStorage.setItem("active_session_id", sessionId);
    else localStorage.removeItem("active_session_id");
  }, [sessionId, isPageLoading]);

  const fetchSessions = async () => {
    try {
      setSessions(await listSessions());
    } catch (err) {
      console.error(err);
    }
  };

  const fetchModels = async () => {
    try {
      const data = await listLlmModels();
      const localModels = data.models || [];
      const proprietary = data.proprietary || [];
      setModels(localModels);
      setProprietaryModels(proprietary);
      const all = [...localModels, ...proprietary];
      if (all.length > 0) {
        const saved = localStorage.getItem("selected_model");
        setSelectedModel(saved && all.includes(saved) ? saved : all[0]);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleSelectSession = async (id: string) => {
    try {
      const data = await getSession(id);
      setSessionId(data.id);
      if (data.filename) {
        setSources([
          {
            name: data.filename,
            type: data.type === "tabular" ? "tabular" : "document",
            meta: data.type === "tabular" ? "Données tabulaires" : "Document PDF/Word",
          },
        ]);
        setLeftTab("sources");
      } else {
        setSources([]);
      }
      setInitialMessage(null);
    } catch (err) {
      console.error(err);
      if (id === localStorage.getItem("active_session_id")) {
        localStorage.removeItem("active_session_id");
      }
    }
  };

  const handleDeleteSession = async (id: string) => {
    if (!confirm("Voulez-vous vraiment supprimer cette discussion ?")) return;
    await deleteSession(id);
    fetchSessions();
    if (sessionId === id) handleNewSession();
  };

  const handleRenameSession = async (id: string, title: string) => {
    const trimmed = title.trim();
    if (!trimmed) return;

    // Mise à jour optimiste de la liste affichée
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title: trimmed } : s)));

    try {
      await renameSession(id, trimmed);
    } catch (err) {
      console.error("Erreur lors du renommage de la session:", err);
      fetchSessions();
    }
  };

  const handleUpload = (data: UploadData) => {
    setSessionId(data.session_id);
    const newSource: SourceItem = {
      name: data.filename || data.profile?.filename || "Source",
      type: data.type === "tabular_analyzed" ? "tabular" : "document",
      meta: data.type === "tabular_analyzed" ? "Données tabulaires" : "Document PDF/Word",
    };
    setSources((s) => [...s, newSource]);
    setLeftTab("sources");
    const text = data.type === "tabular_analyzed" ? data.interpretation ?? "" : data.summary ?? "";
    setInitialMessage({ role: "assistant", text, isSummary: data.type === "tabular_analyzed" });
    fetchSessions();
  };

  const handleRemove = (index: number) => setSources((s) => s.filter((_, i) => i !== index));

  const handleNewSession = () => {
    setSources([]);
    setSessionId(null);
    setInitialMessage(null);
  };

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        await Promise.all([fetchSessions(), fetchModels()]);
        const saved = localStorage.getItem("active_session_id");
        if (saved && mounted) await handleSelectSession(saved);
      } finally {
        if (mounted) setIsPageLoading(false);
      }
    })();
    return () => {
      mounted = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (isPageLoading) {
    return (
      <div className="flex h-screen flex-col gap-2.5 p-2" style={{ background: "var(--bg-app)" }}>
        <div className="flex h-14 items-center gap-3 rounded-lg border px-5" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }}>
          <div className="size-8 animate-pulse rounded-md" style={{ background: "var(--border-color)" }} />
          <div className="h-3 w-32 animate-pulse rounded-full" style={{ background: "var(--border-color)" }} />
        </div>
        <div className="flex flex-1 gap-2.5">
          <div className="w-[22%] animate-pulse rounded-lg border" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }} />
          <div className="flex-1 animate-pulse rounded-lg border" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }} />
          <div className="w-[23%] animate-pulse rounded-lg border" style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden" style={{ background: "var(--bg-app)", color: "var(--text-main)" }}>
      <div
        className="relative z-10 flex h-14 shrink-0 items-center justify-between border-b px-5"
        style={{ background: "var(--bg-panel)", borderColor: "var(--border-color)" }}
      >
        <div className="flex items-center gap-2.5">
          <div className="grid size-7 place-items-center overflow-hidden rounded-md border" style={{ borderColor: "var(--border-color)" }}>
            <Image src="/logo.png" alt="Logo" width={22} height={22} style={{ objectFit: "contain" }} />
          </div>
          <span className="font-serif text-[17px] font-medium tracking-tight" style={{ color: "var(--text-main)" }}>
            No-Code Data Intelligence
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="grid size-8 place-items-center rounded-md border transition-colors hover:bg-[var(--bubble-ai)]"
            style={{ borderColor: "var(--border-color)", color: "var(--text-muted)" }}
          >
            {theme === "dark" ? <Sun size={15} strokeWidth={1.6} /> : <Moon size={15} strokeWidth={1.6} />}
          </button>

          {[
            { label: "Nouvelle session", icon: Plus, action: () => (sources.length > 0 ? setIsNewSessionConfirmOpen(true) : handleNewSession()) },
            { label: "Partager", icon: Share2, action: () => setIsShareOpen(true) },
            { label: "Paramètres", icon: Settings2, action: () => setIsSettingsOpen(true) },
          ].map((btn) => (
            <button
              key={btn.label}
              onClick={btn.action}
              className="hidden items-center gap-1.5 rounded-md border px-3 py-1.5 text-[13px] font-medium transition-colors hover:bg-[var(--bubble-ai)] sm:flex"
              style={{ borderColor: "var(--border-color)", color: "var(--text-muted)" }}
            >
              <btn.icon size={14} strokeWidth={1.6} /> {btn.label}
            </button>
          ))}

          <div ref={avatarRef} className="relative ml-1">
            <button
              onClick={() => setIsAvatarOpen(!isAvatarOpen)}
              className="grid size-8 place-items-center rounded-full text-[13px] font-medium transition-colors"
              style={{ background: "var(--accent)", color: "var(--accent-contrast)" }}
            >
              W
            </button>
            <AvatarMenu isOpen={isAvatarOpen} onClose={() => setIsAvatarOpen(false)} anchorRef={avatarRef} />
          </div>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden p-2">
        <Group orientation="horizontal" style={{ width: "100%", height: "100%" }}>
          <Panel defaultSize={22} minSize={16} style={{ height: "100%" }}>
            <div className="flex h-full flex-col overflow-hidden rounded-lg border" style={{ background: "var(--bg-panel)", borderColor: "var(--border-color)" }}>
              <div className="min-h-0 flex-1">
                <div style={{ display: leftTab === "sources" ? "block" : "none", height: "100%" }}>
                  <SourcesPanel
                    sources={sources}
                    onUpload={handleUpload}
                    onRemove={handleRemove}
                    selectedModel={selectedModel}
                    registerUploadHandler={registerUploadHandler}
                    onProgressChange={setUploadProgress}
                  />
                </div>
                <div style={{ display: leftTab === "history" ? "block" : "none", height: "100%" }}>
                  <HistoryPanel sessions={sessions} currentSessionId={sessionId} onSelectSession={handleSelectSession} onDeleteSession={handleDeleteSession} onRenameSession={handleRenameSession} onNewSession={handleNewSession} />
                </div>
              </div>
              <SideDock activeTab={leftTab} sourceCount={sources.length} onTabChange={setLeftTab} />
            </div>
          </Panel>
          <Separator style={{ width: "8px", background: "transparent", cursor: "col-resize" }} />
          <Panel defaultSize={55} minSize={30} style={{ height: "100%" }}>
            <ChatPanel
              sessionId={sessionId}
              sourceCount={sources.length}
              initialMessage={initialMessage}
              selectedModel={selectedModel}
              uploadProgress={uploadProgress}
              onUploadClick={() => openUpload?.()}
              onAssistantMessage={setGeneratedContent}
            />
          </Panel>
          <Separator style={{ width: "8px", background: "transparent", cursor: "col-resize" }} />
          <Panel defaultSize={23} minSize={16} style={{ height: "100%" }}>
            <StudioPanel sessionId={sessionId} generatedContent={generatedContent} openModels={() => setIsModelsOpen(true)} />
          </Panel>
        </Group>
      </div>

      <div className="flex h-7 shrink-0 items-center justify-center text-[11px]" style={{ color: "var(--text-dim)" }}>
        No-Code Data Intelligence peut se tromper. Veuillez donc vérifier ses réponses.
      </div>

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
        onModelsRefetch={fetchModels}
      />
      <ModelsModal isOpen={isModelsOpen} onClose={() => setIsModelsOpen(false)} sessionId={sessionId} />
      <ShareModal isOpen={isShareOpen} onClose={() => setIsShareOpen(false)} sourcesCount={sources.length} />

      <Modal isOpen={isNewSessionConfirmOpen} onClose={() => setIsNewSessionConfirmOpen(false)} title="Confirmation">
        <div className="flex flex-col gap-4">
          <div className="text-[14px]" style={{ color: "var(--text-main)" }}>
            Êtes-vous sûr de vouloir commencer une nouvelle session ? Toutes vos sources et discussions en cours seront définitivement effacées de l&rsquo;écran.
          </div>
          <div className="mt-1 flex justify-end gap-3">
            <button onClick={() => setIsNewSessionConfirmOpen(false)} className="rounded-md border px-4 py-2 text-[13px] font-medium" style={{ borderColor: "var(--border-color)", color: "var(--text-muted)" }}>
              Annuler
            </button>
            <button
              onClick={() => { handleNewSession(); setIsNewSessionConfirmOpen(false); }}
              className="rounded-md px-5 py-2 text-[13px] font-medium text-white"
              style={{ background: "var(--danger)" }}
            >
              Confirmer
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
