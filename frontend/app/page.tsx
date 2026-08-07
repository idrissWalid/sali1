"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Database, MessageSquare, Plus, Settings2, Share2, Sparkles } from "lucide-react";
import { Panel, Group, Separator, usePanelRef } from "react-resizable-panels";
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
import SaliMark from "./components/SaliMark";
import ThemeToggleButton from "./components/ThemeToggleButton";
import { setTheme, useTheme } from "@/hooks/use-theme";
import { API_URL } from "@/lib/api";
import { PanelLeftOpen } from "@/components/animate-ui/icons/panel-left-open";
import { PanelLeftClose } from "@/components/animate-ui/icons/panel-left-close";

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
  /** Présent quand le fichier importé était un classeur à plusieurs feuilles. */
  feuilles?: {
    total: number;
    principale: string;
    principale_affichage: string;
    ajoutees: string[];
    ignorees: string[];
  } | null;
}

export default function Home() {
  const [sources, setSources] = useState<Source[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [initialMessage, setInitialMessage] = useState<{ role: "assistant"; text: string; isSummary?: boolean } | null>(null);
  // Lu depuis <html>, pas depuis un état local : le dashboard et les vues de
  // modèles écrivent le même attribut. Un état propre à cette page en faisait
  // une seconde source de vérité, et son effet de montage réappliquait « dark »
  // à chaque retour depuis le dashboard — écrasant le choix de l'utilisateur.
  const theme = useTheme();
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [leftTab, setLeftTab] = useState<"sources" | "history">("sources");
  const [openUpload, setOpenUpload] = useState<(() => void) | null>(null);
  const [mobileView, setMobileView] = useState<"data" | "chat" | "studio">("chat");
  const leftPanelRef = usePanelRef();
  const studioPanelRef = usePanelRef();
  const [isLeftPanelOpen, setIsLeftPanelOpen] = useState(true);
  const [isStudioPanelOpen, setIsStudioPanelOpen] = useState(true);

  const toggleLeftPanel = () => {
    if (isLeftPanelOpen) leftPanelRef.current?.collapse();
    else leftPanelRef.current?.expand();
    setIsLeftPanelOpen((open) => !open);
  };

  const toggleStudioPanel = () => {
    if (isStudioPanelOpen) studioPanelRef.current?.collapse();
    else studioPanelRef.current?.expand();
    setIsStudioPanelOpen((open) => !open);
  };

  const registerUploadHandler = useCallback((handler: (() => void) | null) => {
    setOpenUpload(() => handler);
  }, []);

  const [models, setModels] = useState<string[]>([]);
  const [proprietaryModels, setProprietaryModels] = useState<string[]>([]);
  // Pas de modèle figé ici : la valeur vient de /api/llm-models (champ `default`,
  // lui-même piloté par /api/settings/default-model) tant que l'utilisateur n'a
  // rien choisi explicitement (localStorage).
  const [selectedModel, setSelectedModel] = useState<string>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("selected_model") || "";
    }
    return "";
  });

  // Modal & Dropdown visibility states
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isModelsOpen, setIsModelsOpen] = useState(false);
  const [generatedContent, setGeneratedContent] = useState<string>("");
  // Génération de modèle dans le chat : pilote le placeholder animé + le
  // rechargement de la liste des modèles dans le Studio.
  const [chatModelPending, setChatModelPending] = useState(false);
  const [modelsRefreshKey, setModelsRefreshKey] = useState(0);
  const [isShareOpen, setIsShareOpen] = useState(false);
  const [isAvatarOpen, setIsAvatarOpen] = useState(false);
  const [isNewSessionConfirmOpen, setIsNewSessionConfirmOpen] = useState(false);
  const [isPageLoading, setIsPageLoading] = useState(true);

  // Anchor ref for positioning avatar dropdown
  const avatarRef = useRef<HTMLButtonElement>(null);

  // Vrai quand la dernière tentative de restauration a échoué pour une raison
  // passagère : le pointeur de session persisté doit alors être préservé.
  const [restaurationRatee, setRestaurationRatee] = useState(false);

  useEffect(() => {
    // Tant que la restauration initiale (lecture de active_session_id) n'est
    // pas terminée, sessionId vaut encore null : ne pas effacer la valeur
    // persistée sous peine de perdre la session avant même de l'avoir relue
    // (cas typique : retour depuis /dashboard, qui remonte ce composant).
    if (isPageLoading) return;

    if (sessionId) {
      localStorage.setItem("active_session_id", sessionId);
    } else if (!restaurationRatee) {
      // `sessionId` est aussi nul quand la restauration a échoué : sans cette
      // garde, une panne passagère effaçait le pointeur et la session était
      // définitivement perdue, y compris aux rafraîchissements suivants.
      localStorage.removeItem("active_session_id");
    }
  }, [sessionId, isPageLoading, restaurationRatee]);

  // État de la liste des sessions. Un échec ne se voyait nulle part : la barre
  // latérale affichait « Aucune discussion enregistrée », strictement
  // indiscernable d'un compte neuf, pendant que l'erreur partait dans la console.
  const [sessionsState, setSessionsState] = useState<"loading" | "ready" | "error">("loading");

  const fetchSessions = async () => {
    setSessionsState((etat) => (etat === "ready" ? etat : "loading"));
    try {
      const res = await fetch(`${API_URL}/api/sessions`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSessions(data || []);
      setSessionsState("ready");
    } catch (err) {
      console.error("Erreur lors du chargement des sessions:", err);
      setSessionsState("error");
    }
  };

  const fetchModels = async () => {
    try {
      const apiUrl = API_URL;
      const res = await fetch(`${apiUrl}/api/llm-models`);
      const data = await res.json();
      if (data.models) {
        setModels(data.models);
      }
      if (data.proprietary) {
        setProprietaryModels(data.proprietary);
      }
      const allModels = [...(data.models || []), ...(data.proprietary || [])];
      const savedModel = localStorage.getItem("selected_model");
      if (savedModel && allModels.includes(savedModel)) {
        setSelectedModel(savedModel);
      } else if (data.default) {
        setSelectedModel(data.default);
      } else if (allModels.length > 0) {
        setSelectedModel(allModels[0]);
      }
    } catch (err) {
      console.error("Erreur lors du chargement des modèles LLM:", err);
    }
  };


  /** Toutes les sources d'une session, telles que le serveur les connaît.
   *
   * `session.filename` ne nomme que le fichier principal : une session porte
   * aussi le tableau extrait d'un PDF et les fichiers ajoutés en cours de
   * route. Les reconstruire depuis ce seul champ faisait disparaître tous les
   * autres au rafraîchissement, alors qu'ils étaient toujours en base.
   */
  const chargerSources = async (
    id: string, sessionType: string, filenamePrincipal?: string,
  ): Promise<Source[]> => {
    const enSource = (nom: string, estDocument: boolean, version = 1): Source => ({
      name: nom,
      type: estDocument ? "document" : "tabular",
      // Le numéro de version ne s'affiche qu'à partir de la première
      // modification : sinon il ferait du bruit sur un jeu jamais touché.
      meta: (estDocument ? "Document" : "Données tabulaires")
        + (version > 1 ? ` · v${version}` : ""),
    });

    try {
      const res = await fetch(`${API_URL}/api/sessions/${id}/datasets`);
      if (res.ok) {
        const data = await res.json();
        const jeux: { id: string; name?: string; filename?: string; version?: number }[] =
          data.datasets ?? [];
        if (jeux.length > 0) {
          // Seul le fichier principal d'une session document est un document ;
          // les jeux attachés (tableau extrait, ajouts) sont tabulaires.
          return jeux.map((jeu) => enSource(
            jeu.name || jeu.filename || "Source",
            jeu.id === "__main__" && sessionType !== "tabular",
            jeu.version ?? 1,
          ));
        }
      }
    } catch (err) {
      console.error("Liste des jeux de données indisponible :", err);
    }

    // Repli : le fichier principal seul, comme avant — mieux qu'un panneau vide.
    return filenamePrincipal ? [enSource(filenamePrincipal, sessionType !== "tabular")] : [];
  };

  /** Recharge la liste des sources de la session ouverte, après une opération
   *  qui a changé les données (modification demandée depuis le chat). */
  const rechargerSources = async () => {
    if (!sessionId) return;
    const type = sessions.find((s) => s.id === sessionId)?.type ?? "tabular";
    setSources(await chargerSources(sessionId, type));
  };

  /** Charge une session. Renvoie `false` si l'échec est transitoire (le pointeur
   *  persisté est alors conservé, un nouvel essai peut aboutir). */
  const handleSelectSession = async (id: string): Promise<boolean> => {
    try {
      const res = await fetch(`${API_URL}/api/sessions/${id}`);

      // 404 : la session n'existe réellement plus, on peut l'oublier. Toute
      // autre panne est transitoire (backend qui démarre, coupure réseau) :
      // effacer le pointeur ferait perdre la session pour de bon.
      if (res.status === 404) {
        if (id === localStorage.getItem("active_session_id")) {
          localStorage.removeItem("active_session_id");
        }
        return true;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      setRestaurationRatee(false);
      setSessionId(data.id);

      const restaurees = await chargerSources(data.id, data.type, data.filename);
      setSources(restaurees);
      if (restaurees.length > 0) setLeftTab("sources");

      // Pas de message initial lors de la reprise d'une session
      setInitialMessage(null);
      return true;
    } catch (err) {
      console.error("Erreur lors du chargement des détails de la session:", err);
      setRestaurationRatee(true);
      return false;
    }
  };

  const handleDeleteSession = async (id: string) => {
    if (!confirm("Voulez-vous vraiment supprimer cette discussion ?")) return;

    try {
      const apiUrl = API_URL;
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

  const handleRenameSession = async (id: string, title: string) => {
    const trimmed = title.trim();
    if (!trimmed) return;

    // Mise à jour optimiste de la liste affichée
    setSessions(prev => prev.map(s => (s.id === id ? { ...s, title: trimmed } : s)));

    try {
      const apiUrl = API_URL;
      const res = await fetch(`${apiUrl}/api/sessions/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed }),
      });
      if (!res.ok) throw new Error("Erreur serveur");
    } catch (err) {
      console.error("Erreur lors du renommage de la session:", err);
      // En cas d'échec, on resynchronise avec le backend
      fetchSessions();
    }
  };

  const handleUpload = (data: UploadData) => {
    setSessionId(data.session_id);

    // Fichier AJOUTÉ à une session ouverte : il enrichit le contexte existant.
    // La conversation ne repart pas de zéro et le message d'accueil n'est pas
    // remplacé — sans quoi ajouter des métadonnées effacerait l'analyse en cours.
    const ajoutDansSession = data.type === "dataset_added" || data.type === "document_added";
    const estTabulaire = data.type === "tabular_analyzed" || data.type === "dataset_added";

    const newSource: Source = {
      // Un classeur découpé en feuilles est représenté par la feuille retenue,
      // pas par le nom du classeur : c'est ce que la session porte réellement.
      name: data.feuilles?.principale_affichage
        || data.filename || data.profile?.filename || "Source",
      type: estTabulaire ? "tabular" : "document",
      meta: estTabulaire ? "Données tabulaires" : "Document",
    };
    // Les autres feuilles sont devenues des jeux de données à part entière :
    // elles apparaissent immédiatement, sans attendre un rafraîchissement.
    const feuillesJointes: Source[] = (data.feuilles?.ajoutees ?? []).map((nom) => ({
      name: nom,
      type: "tabular",
      meta: "Données tabulaires",
    }));
    setSources(s => [...s, newSource, ...feuillesJointes]);
    setLeftTab("sources");

    if (!ajoutDansSession) {
      const text = data.type === "tabular_analyzed" ? (data.interpretation ?? "") : (data.summary ?? "");
      setInitialMessage({ role: "assistant", text, isSummary: data.type === "tabular_analyzed" });
    }

    // Rafraîchir l'historique des sessions
    fetchSessions();
  };

  const handleRemove = (index: number) => {
    setSources(s => s.filter((_, i) => i !== index));
  };

  const handleNewSession = () => {
    // Départ volontaire : le pointeur persisté doit bien être effacé, la garde
    // de restauration ne s'applique qu'aux échecs subis.
    setRestaurationRatee(false);
    setSources([]);
    setSessionId(null);
    setInitialMessage(null);
  };

  useEffect(() => {
    let isMounted = true;

    const initializeApp = async () => {
      await Promise.all([fetchSessions(), fetchModels()]);
      const savedSessionId = localStorage.getItem("active_session_id");
      if (savedSessionId && isMounted) {
        const restauree = await handleSelectSession(savedSessionId);
        // Un second essai après un court délai : au rechargement de la page,
        // le backend peut n'être pas encore prêt à répondre, et un panneau
        // vide est indiscernable d'une session sans fichier.
        if (!restauree && isMounted) {
          await new Promise((resoudre) => setTimeout(resoudre, 700));
          if (isMounted) await handleSelectSession(savedSessionId);
        }
      }
    };

    // `fetch` n'a pas de délai d'expiration : une requête qui n'aboutit jamais
    // (backend éteint en cours de route, tunnel coupé) laissait la promesse en
    // suspens, donc le squelette de chargement affiché indéfiniment — c'était
    // le seul endroit du composant à lever `isPageLoading`. L'échéance garantit
    // que l'interface s'affiche ; les requêtes lentes qui aboutissent ensuite
    // peuplent l'écran normalement, celles qui échouent laissent leurs états
    // d'erreur respectifs faire leur travail.
    const echeance = new Promise<void>((resoudre) => setTimeout(resoudre, 12_000));

    Promise.race([
      initializeApp().catch((err) => {
        console.error("Initialisation interrompue :", err);
      }),
      echeance,
    ]).finally(() => {
      if (isMounted) setIsPageLoading(false);
    });

    return () => {
      isMounted = false;
    };
    // Initialisation au montage uniquement : réexécuter cet effet à chaque
    // nouvelle identité de `handleSelectSession` rechargerait la session en
    // boucle, à chaque rendu.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    <div className="app-shell">
      <a className="skip-link" href="#main-workspace">Aller à la discussion</a>

      {/* TOPBAR */}
      <header className="app-topbar">

        {/* Gauche : logo Sali AI */}
        <div className="sali-brand" aria-label="Sali AI">
          <div className="sali-brand__chip">
            <SaliMark size={32} color="var(--sali-header-mark)" />
          </div>
          <span className="sali-brand__name">Sali AI</span>
        </div>

        {/* Droite : boutons */}
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>

          {/* Theme Toggle */}
          <ThemeToggleButton
            isDark={theme === "dark"}
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

              // `setTheme` pose l'attribut ET le persiste, en un seul endroit.
              // L'appel reste DANS la transition pour que le dévoilement
              // circulaire capture bien le changement de couleurs.
              if (!document.startViewTransition) {
                setTheme(newTheme);
                return;
              }

              document.startViewTransition(() => setTheme(newTheme));
            }}
          />

          <div className="app-topbar__actions">
            {[
              {
                label: "Nouvelle session", icon: Plus, action: () => {
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
              <button key={i} onClick={btn.action} className="app-topbar__action"
                aria-label={btn.label}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "6px",
                  padding: "7px 16px",
                  borderRadius: "20px",
                  border: "1px solid var(--border-color)",
                  color: "var(--text-muted)",
                  fontSize: "13px",
                  fontFamily: "var(--font-google-sans), sans-serif",
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
                <span>{btn.label}</span>
              </button>
            ))}
            <button
              ref={avatarRef}
              onClick={() => setIsAvatarOpen(!isAvatarOpen)}
              aria-label="Ouvrir le menu du profil"
              aria-expanded={isAvatarOpen}
              style={{
                width: "40px", height: "40px",
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
            </button>
          </div>

          {/* Avatar Menu Dropdown Overlay */}
          <AvatarMenu isOpen={isAvatarOpen} onClose={() => setIsAvatarOpen(false)} anchorRef={avatarRef} />
        </div>

      </header>

      <nav className="mobile-workspace-nav" aria-label="Espaces de travail">
        {([
          { id: "data", label: "Données", icon: Database },
          { id: "chat", label: "Chat", icon: MessageSquare },
          { id: "studio", label: "Studio", icon: Sparkles },
        ] as const).map((item) => (
          <button key={item.id} type="button" aria-pressed={mobileView === item.id} onClick={() => setMobileView(item.id)}>
            <item.icon size={17} aria-hidden="true" />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>

      {/* MAIN */}
      <main id="main-workspace" className="app-workspace" style={{ display: "flex", alignItems: "center" }}>
        <button type="button" className="panel-toggle panel-toggle--left" onClick={toggleLeftPanel}
          aria-label={isLeftPanelOpen ? "Fermer le panneau Données" : "Ouvrir le panneau Données"} aria-expanded={isLeftPanelOpen}>
          {isLeftPanelOpen ? <PanelLeftClose animateOnHover size={19} /> : <PanelLeftOpen animateOnHover size={19} />}
        </button>
        <button type="button" className="panel-toggle panel-toggle--right" onClick={toggleStudioPanel}
          aria-label={isStudioPanelOpen ? "Fermer le panneau Studio" : "Ouvrir le panneau Studio"} aria-expanded={isStudioPanelOpen}>
          <span className="panel-toggle__mirrored">
            {isStudioPanelOpen ? <PanelLeftClose animateOnHover size={19} /> : <PanelLeftOpen animateOnHover size={19} />}
          </span>
        </button>
        <Group orientation="horizontal" className="workspace-panels" style={{ width: "100%", height: "98%", margin: "auto" }}>
          <Panel panelRef={leftPanelRef} defaultSize={22} minSize={15} collapsible collapsedSize={0} className={`workspace-panel workspace-panel--data${mobileView === "data" ? " is-mobile-active" : ""}`} style={{ height: "100%" }}>
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
                    // Session ouverte : les fichiers suivants s'y rattachent au
                    // lieu d'ouvrir une session à chaque import.
                    sessionId={sessionId}
                  />
                </div>
                <div style={{ display: leftTab === "history" ? "flex" : "none", height: "100%", flexDirection: "column" }}>
                  <Sidebar
                    sessions={sessions}
                    currentSessionId={sessionId}
                    onSelectSession={handleSelectSession}
                    onDeleteSession={handleDeleteSession}
                    onRenameSession={handleRenameSession}
                    onNewSession={handleNewSession}
                    hideHeader={true}
                    state={sessionsState}
                    onRetry={fetchSessions}
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
          <Separator className="workspace-separator" style={{ width: "8px" }} />
          <Panel defaultSize={55} minSize={30} className={`workspace-panel workspace-panel--chat${mobileView === "chat" ? " is-mobile-active" : ""}`} style={{ width: "100%" }}>
            <ChatPanel
              onDatasetChanged={rechargerSources}
              sessionId={sessionId}
              sourceCount={sources.length}
              initialMessage={initialMessage}
              selectedModel={selectedModel}
              onUploadClick={() => openUpload?.()}
              onAssistantMessage={(text) => setGeneratedContent(text)}
              onModelActivity={(activity) => {
                if (activity.status === "start") {
                  setChatModelPending(true);
                } else {
                  setChatModelPending(false);
                  // Recharge la liste des modèles du Studio (le nouveau apparaît).
                  setModelsRefreshKey((k) => k + 1);
                }
              }}
            />
          </Panel>
          <Separator className="workspace-separator" style={{ width: "8px" }} />
          <Panel panelRef={studioPanelRef} defaultSize={23} minSize={15} collapsible collapsedSize={0} className={`workspace-panel workspace-panel--studio${mobileView === "studio" ? " is-mobile-active" : ""}`} style={{ height: "100%" }}>
            <StudioPanel sessionId={sessionId} generatedContent={generatedContent} chatModelPending={chatModelPending} modelsRefreshKey={modelsRefreshKey} />
          </Panel>
        </Group>
      </main>

      {/* FOOTER */}
      <footer className="app-disclaimer">
        No-Code Data Intelligence peut se tromper. Veuillez donc vérifier ses réponses.
      </footer>

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
        onModelsRefetch={fetchModels}
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
