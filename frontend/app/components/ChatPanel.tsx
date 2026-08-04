"use client";
import { useState, useRef, useEffect } from "react";
import type { CSSProperties, JSX, ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import TextType from "./TextType";
import ChatSettingsModal from "./ChatSettingsModal";
import ChatMoreMenu from "./ChatMoreMenu";
import ImageLightbox from "./ImageLightbox";
import { ImageZoom, Image } from "./ImageZoom";
import Modal from "./Modal";
import { PlaceholdersAndVanishInput } from "./PlaceholdersAndVanishInput";
import WelcomePanel from "./WelcomePanel";
import SaliMark, { SaliLoadingMark } from "./SaliMark";
import { API_URL } from "@/lib/api";
import { readUserPreferences, USER_PREFERENCES_EVENT } from "@/lib/user-preferences";
import {
  FileText, MoreVertical, Settings2,
  Search, BookOpen, Code2, Play, Lightbulb, PenLine, Sparkles,
} from "lucide-react";

// Icône associée à chaque phase annoncée par le backend (champ `phase`).
const STEP_ICONS: Record<string, typeof Search> = {
  searching: Search,
  reading: BookOpen,
  coding: Code2,
  executing: Play,
  compute: Sparkles,
  interpreting: Lightbulb,
  writing: PenLine,
};

interface Message {
  role: "user" | "assistant";
  text: string;
  images?: string[];
  isSummary?: boolean;
  sources?: { page: number; text: string }[];
}

interface Props {
  sessionId: string | null;
  sourceCount: number;
  initialMessage: Message | null;
  selectedModel?: string;
  onUploadClick?: () => void;
  onAssistantMessage?: (text: string) => void;
  // Signale au parent qu'un modèle est en cours de génération dans le chat
  // ("start") puis qu'il est terminé ("done", avec l'id si un modèle a été créé).
  onModelActivity?: (activity: { status: "start" } | { status: "done"; modelId?: string | null }) => void;
}

// Helper pour parser le gras et le code inline
type SourceRef = { page: number; text: string };

// Rend une citation inline "[n]" (insérée par le LLM) en badge cliquable qui
// ouvre l'extrait source correspondant (msg.sources[n-1]). Sans sources
// disponibles, le texte "[n]" reste affiché tel quel.
function renderCitation(part: string, key: number, sources?: SourceRef[], onSourceClick?: (src: SourceRef) => void): ReactNode {
  const match = part.match(/^\[(\d+)\]$/);
  const index = match ? parseInt(match[1], 10) : NaN;
  const source = sources && index >= 1 ? sources[index - 1] : undefined;

  if (!source || !onSourceClick) {
    return <span key={key}>{part}</span>;
  }

  return (
    <button
      key={key}
      onClick={() => onSourceClick(source)}
      title={`Voir la source (page ${source.page})`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        minWidth: "15px",
        height: "15px",
        padding: "0 4px",
        margin: "0 1px",
        borderRadius: "999px",
        border: "1px solid var(--accent-color)",
        background: "var(--accent-soft)",
        color: "var(--accent-color)",
        fontSize: "10px",
        fontWeight: 700,
        lineHeight: 1,
        verticalAlign: "super",
        cursor: "pointer",
      }}
    >
      {index}
    </button>
  );
}

function renderInlineMarkdown(text: string, sources?: SourceRef[], onSourceClick?: (src: SourceRef) => void): ReactNode[] {
  const parts = text.split(/(\*\*.*?\*\*|`.*?`|\[\d+\])/g);
  return parts.map((part, j) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={j} style={{ fontWeight: 600, color: "var(--text-main)" }}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={j} style={{
          background: "var(--border-color)",
          padding: "2px 6px",
          borderRadius: "4px",
          fontSize: "12px",
          fontFamily: "var(--font-roboto-mono), monospace",
        }}>
          {part.slice(1, -1)}
        </code>
      );
    }
    if (/^\[\d+\]$/.test(part)) {
      return renderCitation(part, j, sources, onSourceClick);
    }
    return <span key={j}>{part}</span>;
  });
}

// ── Détection / parsing des tableaux Markdown (GFM) ──────────
function splitTableRow(line: string): string[] {
  let trimmed = line.trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
  return trimmed.split("|").map(c => c.trim());
}

function isTableSeparatorRow(line: string, expectedCols: number): boolean {
  const trimmed = line.trim();
  if (!/^[:\-|\s]+$/.test(trimmed) || !trimmed.includes("-")) return false;
  const cells = splitTableRow(trimmed);
  return cells.length === expectedCols && cells.every(c => /^:?-+:?$/.test(c));
}

type ColAlign = "left" | "center" | "right";

function renderTable(headerCells: string[], alignCells: string[], rows: string[][], key: string): ReactNode {
  const aligns: ColAlign[] = alignCells.map(c => {
    const left = c.startsWith(":");
    const right = c.endsWith(":");
    if (left && right) return "center";
    if (right) return "right";
    return "left";
  });

  return (
    <div key={key} style={{ overflowX: "auto", margin: "10px 0", borderRadius: "10px", border: "1px solid var(--border-color)" }}>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: "13px" }}>
        <thead>
          <tr>
            {headerCells.map((h, ci) => (
              <th
                key={ci}
                style={{
                  textAlign: aligns[ci] || "left",
                  padding: "9px 14px",
                  borderBottom: "2px solid var(--border-color)",
                  fontWeight: 600,
                  color: "var(--text-main)",
                  background: "var(--bubble-ai)",
                  whiteSpace: "nowrap",
                }}
              >
                {renderInlineMarkdown(h)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri} style={{ background: ri % 2 === 1 ? "var(--bg-panel)" : "transparent" }}>
              {headerCells.map((_, ci) => (
                <td
                  key={ci}
                  style={{
                    textAlign: aligns[ci] || "left",
                    padding: "9px 14px",
                    borderBottom: "1px solid var(--border-muted)",
                    color: "var(--text-main)",
                    verticalAlign: "top",
                  }}
                >
                  {renderInlineMarkdown(row[ci] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Rendu markdown amélioré ──────────────────────────────────
// `section` permet de scinder le texte en deux blocs : le contenu principal
// ("content") et les suggestions/propositions détectées en fin de réponse
// ("suggestions"), pour pouvoir intercaler les graphiques entre les deux.
function renderMarkdown(
  text: string,
  onPropositionClick?: (text: string) => void,
  section: "all" | "content" | "suggestions" = "all",
  sources?: SourceRef[],
  onSourceClick?: (src: SourceRef) => void
): ReactNode[] {
  const lines = text.split("\n");
  let inPropositions = false;
  const nodes: ReactNode[] = [];
  const shouldInclude = () =>
    section === "all" || (section === "content" ? !inPropositions : inPropositions);

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const cleanLine = line.trim();

    // 0. Détection des tableaux (GFM: ligne d'en-tête + ligne séparatrice |---|---|)
    if (cleanLine.includes("|") && i + 1 < lines.length) {
      const headerCells = splitTableRow(cleanLine);
      if (headerCells.length >= 2 && isTableSeparatorRow(lines[i + 1], headerCells.length)) {
        const alignCells = splitTableRow(lines[i + 1]);
        let j = i + 2;
        const rows: string[][] = [];
        while (j < lines.length && lines[j].trim().includes("|")) {
          rows.push(splitTableRow(lines[j]));
          j++;
        }
        if (shouldInclude()) nodes.push(renderTable(headerCells, alignCells, rows, `table-${i}`));
        i = j - 1;
        continue;
      }
    }

    // 1. Détection des titres (headers) ou pseudo-titres en gras
    let isHeader = false;
    let level = 3;
    let content = "";

    const headerMatch = cleanLine.match(/^(#{1,6})\s+(.*)$/);
    const boldHeaderMatch = cleanLine.match(/^\*\*([^*]+)\*\*\s*:?$/);

    if (headerMatch) {
      isHeader = true;
      level = headerMatch[1].length; // 1 à 6
      content = headerMatch[2];
    } else if (boldHeaderMatch) {
      isHeader = true;
      level = 3;
      content = boldHeaderMatch[1];
    }

    if (isHeader) {
      const HeaderTag = `h${level}` as keyof JSX.IntrinsicElements;
      const upperContent = content.toUpperCase();

      if (
        upperContent.includes("PROPOSITION") ||
        upperContent.includes("SUGGESTION") ||
        upperContent.includes("QUESTION") ||
        upperContent.includes("IDÉE") ||
        upperContent.includes("IDEE")
      ) {
        inPropositions = true;
      } else if (level <= 3) {
        // Si on rencontre un autre grand titre, on sort de la section propositions
        inPropositions = false;
      }

      const style: CSSProperties = {
        margin: level === 1 ? "18px 0 10px" : level === 2 ? "16px 0 8px" : "12px 0 6px",
        fontWeight: 600,
        fontSize: level === 1 ? "18px" : level === 2 ? "16px" : level === 3 ? "14px" : "13px",
        color: "var(--text-main)",
        lineHeight: 1.4,
      };

      if (shouldInclude()) nodes.push(<HeaderTag key={i} style={style}>{renderInlineMarkdown(content, sources, onSourceClick)}</HeaderTag>);
      continue;
    }

    // 2. Détection des listes à puces (bullet points) ou numérotées
    const isBullet = cleanLine.startsWith("- ") || cleanLine.startsWith("* ") || cleanLine.startsWith("• ");
    const numMatch = cleanLine.match(/^(\d+)\.\s+(.*)$/);

    if (isBullet || numMatch) {
      let listContent = "";
      let prefix = "";
      if (isBullet) {
        listContent = cleanLine.substring(2);
        prefix = "•";
      } else {
        prefix = numMatch![1] + ".";
        listContent = numMatch![2];
      }

      if (inPropositions && onPropositionClick) {
        // En mode proposition, on rend une bulle cliquable
        if (shouldInclude()) {
          nodes.push(
            <button
              type="button"
              key={i}
              onClick={() => onPropositionClick(listContent.replace(/\*\*/g, ""))} // Enlève le gras pour l'input
              style={{
                margin: "8px 0 8px 12px",
                padding: "10px 14px",
                background: "var(--bg-app)",
                border: "1px solid var(--accent-color)",
                borderRadius: "14px",
                color: "var(--accent-color)",
                fontSize: "13px",
                fontWeight: 500,
                cursor: "pointer",
                transition: "all 0.2s",
                display: "inline-block",
                width: "fit-content",
                maxWidth: "95%",
                textAlign: "left",
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background = "var(--accent-color)";
                e.currentTarget.style.color = "var(--bg-app)";
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background = "var(--bg-app)";
                e.currentTarget.style.color = "var(--accent-color)";
              }}
            >
              {renderInlineMarkdown(listContent, sources, onSourceClick)}
            </button>
          );
        }
        continue;
      }

      if (shouldInclude()) {
        nodes.push(
          <div key={i} style={{ display: "flex", gap: "8px", margin: "6px 0 6px 12px", alignItems: "flex-start" }}>
            <span style={{ color: "var(--accent-color)", fontWeight: numMatch ? "bold" : "normal", fontSize: numMatch ? "13px" : "inherit", marginTop: numMatch ? "0" : "1px" }}>{prefix}</span>
            <span style={{ flex: 1 }}>{renderInlineMarkdown(listContent, sources, onSourceClick)}</span>
          </div>
        );
      }
      continue;
    }

    // 4. Paragraphe classique ou ligne vide
    if (cleanLine === "") {
      if (shouldInclude()) nodes.push(<div key={i} style={{ height: "8px" }} />);
      continue;
    }

    const upperLine = cleanLine.toUpperCase();
    if (
      upperLine.includes("PROPOSITION") ||
      upperLine.includes("SUGGESTION") ||
      upperLine.includes("QUESTION") ||
      upperLine.includes("IDÉE") ||
      upperLine.includes("IDEE")
    ) {
      inPropositions = true;
    }

    if (shouldInclude()) {
      nodes.push(
        <p key={i} style={{ margin: "4px 0" }}>
          {renderInlineMarkdown(line, sources, onSourceClick)}
        </p>
      );
    }
  }

  return nodes;
}
// ─────────────────────────────────────────────────────────────

export default function ChatPanel({ sessionId, sourceCount, initialMessage, selectedModel, onUploadClick, onAssistantMessage, onModelActivity }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const latestInput = useRef("");

  useEffect(() => {
    latestInput.current = input;
  }, [input]);
  const [loading, setLoading] = useState(false);
  const [textAnimationsEnabled, setTextAnimationsEnabled] = useState(
    () => readUserPreferences().textAnimations,
  );
  // Étape en cours annoncée par le backend, affichée à la place des trois points.
  const [activeStep, setActiveStep] = useState<{ phase: string; message: string } | null>(null);
  const [typingDone, setTypingDone] = useState<Set<number>>(new Set());
  // Titre de la session, généré à l'import d'après le contenu du fichier.
  const [sessionTitle, setSessionTitle] = useState<string>("");
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<{ page: number; text: string } | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const initialMessageAdded = useRef(false); // ← évite le doublon

  // State & Ref for Chat settings and options dropdown
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isMoreMenuOpen, setIsMoreMenuOpen] = useState(false);
  const moreMenuRef = useRef<HTMLButtonElement>(null);

  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const updatePreferences = () => {
      setTextAnimationsEnabled(readUserPreferences().textAnimations);
    };
    window.addEventListener(USER_PREFERENCES_EVENT, updatePreferences);
    window.addEventListener("storage", updatePreferences);
    return () => {
      window.removeEventListener(USER_PREFERENCES_EVENT, updatePreferences);
      window.removeEventListener("storage", updatePreferences);
    };
  }, []);

  const clearChat = () => {
    setMessages([]);
    setTypingDone(new Set());
    initialMessageAdded.current = false;
  };

  const toggleRecording = async () => {
    if (isRecording) {
      if (mediaRecorderRef.current) {
        mediaRecorderRef.current.stop();
        setIsRecording(false);
      }
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append("file", audioBlob, "recording.webm");

        try {
          setLoading(true);
          const apiUrl = API_URL;
          const res = await fetch(`${apiUrl}/api/audio/transcribe`, {
            method: "POST",
            body: formData,
          });
          if (!res.ok) throw new Error("Erreur de transcription");
          const data = await res.json();
          if (data.text) {
            const currentInput = latestInput.current;
            const finalMessage = currentInput.trim() ? `${currentInput} ${data.text}` : data.text;

            // Clear input directly
            setInput("");

            // Send message automatically
            await sendMessage(finalMessage);
          }
        } catch (err) {
          console.error("Erreur de transcription:", err);
          alert("Erreur lors de la transcription vocale.");
          setLoading(false);
        }

        // Stop all tracks
        stream.getTracks().forEach(track => track.stop());
      };

      mediaRecorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error("Erreur d'accès au microphone:", err);
      alert("Impossible d'accéder au microphone.");
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  // Ajout du message initial une seule fois par session
  useEffect(() => {
    if (initialMessage && !initialMessageAdded.current) {
      initialMessageAdded.current = true;
      setMessages([initialMessage]);
    }
  }, [initialMessage]);

  const [prevSessionId, setPrevSessionId] = useState<string | null>(sessionId);
  if (sessionId !== prevSessionId) {
    setPrevSessionId(sessionId);
    // Le titre appartient à la session quittée : le vider tout de suite évite
    // qu'il coiffe brièvement le contenu de la suivante.
    setSessionTitle("");
    if (!sessionId) {
      setMessages([]);
      setTypingDone(new Set());
    }
  }

  useEffect(() => {
    if (!sessionId) {
      initialMessageAdded.current = false;
    }
  }, [sessionId]);

  // Charger l'historique ou reset quand sessionId change (nouvelle session)
  useEffect(() => {
    if (!sessionId) return;
    const fetchHistory = async () => {
      try {
        setLoading(true);
        const apiUrl = API_URL;
        const res = await fetch(`${apiUrl}/api/sessions/${sessionId}`);
        if (!res.ok) throw new Error("Erreur serveur");
        const data = await res.json();

        // « Nouvelle session » est le libellé par défaut en base : ne pas le
        // hisser en gros titre au-dessus du résumé.
        const titre = (data?.title || "").trim();
        setSessionTitle(titre === "Nouvelle session" ? "" : titre);

        if (data && data.messages?.length) {
          setMessages(data.messages);

          // Marquer les anciens messages comme tapés pour éviter l'animation d'écriture
          const doneSet = new Set<number>();
          data.messages.forEach((_: Message, idx: number) => doneSet.add(idx));
          setTypingDone(doneSet);
        } else if (initialMessage) {
          // L'analyse retournée après l'upload peut ne pas être encore persistée.
          setMessages([initialMessage]);
        }
      } catch (err) {
        console.error("Erreur lors du chargement de l'historique:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchHistory();
  }, [sessionId, initialMessage]);

  const sendMessage = async (text: string) => {
    if (!text || !sessionId || loading) return;
    setMessages(m => [...m, { role: "user", text }]);
    setLoading(true);
    const controller = new AbortController();
    abortControllerRef.current = controller;
    // Suivi de l'activité "génération de modèle" pour signaler le parent.
    let modelActivityStarted = false;
    let resultModelId: string | null = null;
    try {
      const apiUrl = API_URL;
      const selected = selectedModel?.trim();
      // Flux NDJSON : le backend annonce chaque étape (recherche de passages,
      // génération de code, interprétation…) avant d'envoyer la réponse finale.
      const res = await fetch(`${apiUrl}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: text,
          ...(selected ? { model: selected } : {}),
        }),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        const error = await res.text();
        throw new Error(error || `Erreur serveur (${res.status})`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let data: { response?: string; images?: string[]; sources?: unknown[]; model_id?: string | null } | null = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Une ligne complète = un événement ; le reliquat attend la suite.
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const event = JSON.parse(line);
          if (event.type === "step") {
            setActiveStep({ phase: event.phase, message: event.message });
            // Un modèle commence à être généré → prévenir le parent (placeholder animé).
            if (event.phase === "model_generating" && !modelActivityStarted) {
              modelActivityStarted = true;
              onModelActivity?.({ status: "start" });
            }
          } else if (event.type === "result") {
            data = event;
          } else if (event.type === "error") {
            throw new Error(event.message);
          }
        }
      }

      if (!data) throw new Error("Aucune réponse reçue du serveur.");
      const textResponse = data.response ?? "";
      resultModelId = data.model_id ?? null;
      setMessages(m => [...m, {
        role: "assistant",
        text: textResponse,
        images: data.images || [],
        sources: (data.sources as Message["sources"]) || [],
      }]);
      onAssistantMessage?.(textResponse);
    } catch (err: unknown) {
      // `unknown` plutôt que `any` : l'abort volontaire (bouton « interrompre »)
      // doit être distingué d'une vraie panne réseau, et le compilateur vérifie
      // désormais ce rétrécissement de type.
      if (err instanceof Error && err.name === "AbortError") {
        setMessages(m => [...m, { role: "assistant", text: "Réponse interrompue." }]);
      } else {
        setMessages(m => [...m, { role: "assistant", text: "Erreur de connexion au serveur." }]);
      }
    } finally {
      setLoading(false);
      setActiveStep(null);
      abortControllerRef.current = null;
      // Fin de génération de modèle : le parent arrête l'animation et rafraîchit
      // la liste des modèles (le nouveau devient cliquable s'il a été créé).
      if (modelActivityStarted) {
        onModelActivity?.({ status: "done", modelId: resultModelId });
      }
    }
  };

  const send = async () => {
    const userMsg = input.trim();
    // Le champ reste saisissable en permanence : la condition d'envoi ne peut
    // plus reposer sur le seul attribut `disabled` du bouton.
    if (!userMsg || !sessionId || loading) return;
    setInput("");
    await sendMessage(userMsg);
  };

  const CHAT_PLACEHOLDERS = [
    "Posez votre question sur vos données...",
    "Quelles sont les tendances principales ?",
    "Résume ce document en 3 points clés.",
    "Compare les colonnes A et B...",
    "Génère un graphique de la distribution.",
    "Quelles anomalies détectes-tu ?",
  ];

  return (
    <div className="chat-panel" style={{
      flex: 1,
      height: "100%",
      minHeight: 0,
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
      background: "var(--bg-chat)",
      borderRadius: "12px",
      border: "1px solid var(--border-color)",
      borderBottom: "none",
    }}>

      {/* Header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "16px 24px",
        borderBottom: "1px solid var(--border-muted)",
        flexShrink: 0,
        position: "relative",
      }}>
        <span style={{ fontFamily: "var(--font-google-sans), sans-serif", fontSize: "16px", fontWeight: 500, color: "var(--text-main)" }}>
          Discussion
        </span>

        <div style={{ display: "flex", gap: "8px" }}>
          {loading && (
            <button
              aria-label="Interrompre la réponse"
              onClick={() => {
                if (abortControllerRef.current) abortControllerRef.current.abort();
                setLoading(false);
              }}
              title="Interrompre la réponse"
              style={{
                width: "36px", height: "36px", borderRadius: "50%",
                display: "flex", alignItems: "center", justifyContent: "center",
                color: "var(--text-muted)", fontSize: "16px", cursor: "pointer",
                border: "none", background: "transparent",
                transition: "background 0.2s",
              }}
              onMouseEnter={e => e.currentTarget.style.background = "var(--bubble-ai)"}
              onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          )}
          <button
            onClick={() => setIsSettingsOpen(true)}
            aria-label="Réglages de la discussion"
            style={{
              width: "36px", height: "36px", borderRadius: "50%",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--text-muted)", fontSize: "16px", cursor: "pointer",
              border: "none", background: "transparent",
              transition: "background 0.2s",
            }}
            onMouseEnter={e => e.currentTarget.style.background = "var(--bubble-ai)"}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
          >
            <Settings2 size={17} strokeWidth={1.8} />
          </button>
          <button
            ref={moreMenuRef}
            onClick={() => setIsMoreMenuOpen(!isMoreMenuOpen)}
            aria-label="Plus d’options"
            aria-expanded={isMoreMenuOpen}
            style={{
              width: "36px", height: "36px", borderRadius: "50%",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--text-muted)", fontSize: "16px", cursor: "pointer",
              border: "none", background: "transparent",
              transition: "background 0.2s",
            }}
            onMouseEnter={e => e.currentTarget.style.background = "var(--bubble-ai)"}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
          >
            <MoreVertical size={18} strokeWidth={1.8} />
          </button>
        </div>
      </div>

      {/* More Menu Dropdown Overlay */}
      <ChatMoreMenu
        isOpen={isMoreMenuOpen}
        onClose={() => setIsMoreMenuOpen(false)}
          anchorRef={moreMenuRef}
          messages={messages}
        onClearChat={clearChat}
      />

      {/* Zone messages + input flottant */}
      <div className="chat-panel-body" style={{ flex: 1, minHeight: 0, position: "relative", display: "flex", flexDirection: "column", overflow: "hidden" }}>

        {/* Messages */}
        {/* `role="log"` annonce les réponses de l'agent aux lecteurs d'écran au
            fil de leur arrivée. Sans lui, l'indicateur d'étapes plus bas était
            la SEULE chose annoncée : l'utilisateur entendait « Interprétation
            des résultats… » puis plus rien, la réponse elle-même restant muette.
            `aria-relevant="additions"` limite l'annonce aux messages ajoutés,
            pour ne pas relire tout l'historique à chaque tour. */}
        <div
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          aria-label="Conversation avec l'agent"
          className={messages.length === 0 ? "chat-messages chat-messages--empty" : "chat-messages"}
          style={{ flex: 1, overflowY: "auto", padding: "24px", paddingBottom: "24px", minHeight: 0 }}
        >

          {messages.length === 0 && sourceCount === 0 && (
            <WelcomePanel onUpload={() => onUploadClick?.()} />
          )}

          {messages.length === 0 && sourceCount > 0 && (
            <div className="chat-empty-message">
              Votre source est prête. Posez votre première question.
            </div>
          )}

          {sessionTitle && messages.length > 0 && (
            <h1
              className="chat-reading-column"
              style={{
                fontSize: "28px",
                fontWeight: 700,
                lineHeight: 1.25,
                letterSpacing: "-0.02em",
                color: "var(--text-main)",
                margin: "4px 0 24px",
                animation: "msgFadeIn 0.25s ease-out both",
              }}
            >
              {sessionTitle}
            </h1>
          )}

          {/* renderMarkdown reçoit sendMessage comme callback ; aucune ref n'est lue
              pendant ce rendu, elles ne le sont qu'à l'exécution du callback. */}
          {/* eslint-disable-next-line react-hooks/refs */}
          {messages.map((msg, i) => (
            <div key={i} className="chat-message-row" style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "flex-start",
              justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
              marginBottom: "24px",
              animation: "msgFadeIn 0.25s ease-out both",
            }}>
              {msg.role === "assistant" && (
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0, order: 0, marginRight: "10px", marginTop: "4px",
                }}><SaliMark size={30} /></div>
              )}
              <div style={{
                maxWidth: msg.role === "user" ? "75%" : "none",
                width: "auto",
                minWidth: 0,
                flex: msg.role === "assistant" ? 1 : undefined,
                order: 1,
                fontSize: "14px",
                lineHeight: 1.75,
                textAlign: msg.role === "assistant" ? "justify" : "left",
                color: "var(--text-main)",
                padding: msg.role === "user" ? "13px 17px" : "4px 0",
                borderRadius: msg.role === "user" ? "20px 4px 20px 20px" : 0,
                background: msg.role === "user"
                  ? "linear-gradient(135deg, rgba(138,180,248,0.18), rgba(167,139,250,0.12))"
                  : "transparent",
                border: msg.role === "user" ? "1px solid rgba(138,180,248,0.28)" : "none",
                boxShadow: msg.role === "user" ? "0 2px 12px rgba(138,180,248,0.1)" : "none",
              }}>
                {msg.role === "assistant" ? (
                  typingDone.has(i) || !textAnimationsEnabled ? (
                    // Typing terminé → rendu markdown
                    <div>
                      {renderMarkdown(msg.text, sendMessage, "content", msg.sources, setSelectedSource)}
                      {msg.isSummary && (
                        <button
                          onClick={() => window.open(`/dashboard/${sessionId}`, "_blank", "noopener,noreferrer")}
                          style={{
                            marginTop: "16px",
                            padding: "10px 16px",
                            background: "var(--accent-color)",
                            color: "var(--bg-app)",
                            border: "none",
                            borderRadius: "8px",
                            fontWeight: 600,
                            cursor: "pointer",
                            fontSize: "13px",
                            display: "flex",
                            alignItems: "center",
                            gap: "8px",
                            transition: "opacity 0.2s"
                          }}
                          onMouseEnter={e => e.currentTarget.style.opacity = "0.85"}
                          onMouseLeave={e => e.currentTarget.style.opacity = "1"}
                        >
                          <span style={{ display: "inline-flex", alignItems: "center" }}>
                            <svg width="18" height="18" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                              <path d="M2.4 13.2A1.2 1.2 0 0 1 3.6 12H6a1.2 1.2 0 0 1 1.2 1.2v6A1.2 1.2 0 0 1 6 20.4H3.6a1.2 1.2 0 0 1-1.2-1.2v-6Zm7.2-4.8a1.2 1.2 0 0 1 1.2-1.2h2.4a1.2 1.2 0 0 1 1.2 1.2v10.8a1.2 1.2 0 0 1-1.2 1.2h-2.4a1.2 1.2 0 0 1-1.2-1.2V8.4Zm7.2-3.6A1.2 1.2 0 0 1 18 3.6h2.4a1.2 1.2 0 0 1 1.2 1.2v14.4a1.2 1.2 0 0 1-1.2 1.2H18a1.2 1.2 0 0 1-1.2-1.2V4.8Z"></path>
                            </svg>
                          </span> Voir le Dashboard interactif
                        </button>
                      )}

                      {/* Images générées par la sandbox — avant les suggestions */}
                      {msg.images && msg.images.length > 0 && (
                        <div style={{ marginTop: "12px", display: "flex", flexDirection: "column", gap: "10px" }}>
                          {msg.images.map((img, j) => (
                            <ImageZoom
                              key={j}
                              style={{
                                width: "100%",
                                borderRadius: "10px",
                                border: "1px solid var(--border-color)",
                              }}
                            >
                              <Image
                                src={`data:image/png;base64,${img}`}
                                alt={`Visualisation ${j + 1}`}
                              />
                            </ImageZoom>
                          ))}
                        </div>
                      )}

                      {renderMarkdown(msg.text, sendMessage, "suggestions")}

                      {/* Sources cliquables */}
                      {msg.sources && msg.sources.length > 0 && (
                        <div style={{
                          marginTop: "14px",
                          borderTop: "1px solid var(--border-muted)",
                          paddingTop: "10px"
                        }}>
                          <div style={{
                            fontSize: "11px",
                            fontWeight: 600,
                            color: "var(--text-muted)",
                            marginBottom: "8px",
                            textTransform: "uppercase",
                            letterSpacing: "0.5px"
                          }}>
                            Sources & Références :
                          </div>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                            {msg.sources.map((src, idx) => (
                              <button
                                key={idx}
                                onClick={() => setSelectedSource(src)}
                                style={{
                                  display: "flex",
                                  alignItems: "center",
                                  gap: "6px",
                                  background: "var(--bg-panel)",
                                  border: "1px solid var(--border-color)",
                                  borderRadius: "16px",
                                  padding: "4px 10px",
                                  fontSize: "12px",
                                  color: "var(--text-main)",
                                  cursor: "pointer",
                                  transition: "all 0.15s",
                                }}
                                onMouseEnter={e => {
                                  e.currentTarget.style.borderColor = "var(--accent-color)";
                                  e.currentTarget.style.background = "var(--accent-soft)";
                                }}
                                onMouseLeave={e => {
                                  e.currentTarget.style.borderColor = "var(--border-color)";
                                  e.currentTarget.style.background = "var(--bg-panel)";
                                }}
                              >
                                <FileText size={13} strokeWidth={1.8} /> Page {src.page}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    // Typing en cours → texte brut animé
                    <TextType
                      text={msg.text || ""}
                      loop={false}
                      typingSpeed={5}
                      showCursor={true}
                      cursorCharacter="|"
                      renderText={(text) => renderMarkdown(text, sendMessage, "all", msg.sources, setSelectedSource)}
                      onComplete={() => {
                        setTypingDone(prev => new Set([...prev, i]));
                      }}
                    />
                  )
                ) : (
                  msg.text
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="chat-message-row" role="status" aria-live="polite" aria-atomic="true" style={{ display: "flex", marginBottom: "24px", animation: "msgFadeIn 0.25s ease-out both" }}>
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "center",
                marginRight: "10px", flexShrink: 0,
              }}><SaliLoadingMark size={30} /></div>
              <div style={{
                display: "flex", alignItems: "center", gap: "6px",
              }}>
                <style>{`
                  @keyframes msgFadeIn {
                    from { opacity: 0; transform: translateY(8px); }
                    to   { opacity: 1; transform: translateY(0); }
                  }
                  @keyframes chat-dot-bounce {
                    0%, 80%, 100% { transform: scale(0.7); opacity: 0.4; }
                    40%           { transform: scale(1.1); opacity: 1; }
                  }
                  .chat-dot {
                    width: 7px; height: 7px; border-radius: 50%;
                    animation: chat-dot-bounce 1.2s ease-in-out infinite;
                  }
                  .chat-step-label {
                    display: inline-block;
                    font-size: 13.5px; font-weight: 500; white-space: nowrap;
                    color: var(--text-muted);
                  }
                `}</style>
                {activeStep ? (
                  <>
                    {activeStep.phase !== "thinking" && (() => {
                      const StepIcon = STEP_ICONS[activeStep.phase] ?? Sparkles;
                      return <StepIcon size={15} strokeWidth={1.9} style={{ color: "#a78bfa", flexShrink: 0 }} />;
                    })()}
                    {textAnimationsEnabled ? (
                      <span style={{ display: "inline-flex", overflow: "hidden", paddingBlock: "2px" }}>
                        <AnimatePresence initial={false} mode="popLayout">
                          <motion.span
                            key={`${activeStep.phase}:${activeStep.message}`}
                            className="chat-step-label"
                            initial={{ opacity: 0, y: "100%" }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: "-100%" }}
                            transition={{ duration: 0.3, ease: "easeInOut" }}
                          >
                            {activeStep.message}
                          </motion.span>
                        </AnimatePresence>
                      </span>
                    ) : (
                      <span className="chat-step-label">{activeStep.message}</span>
                    )}
                  </>
                ) : (
                  <>
                    <span className="chat-dot" style={{ background: "#8ab4f8", animationDelay: "0s" }} />
                    <span className="chat-dot" style={{ background: "#a78bfa", animationDelay: "0.2s" }} />
                    <span className="chat-dot" style={{ background: "#c58af9", animationDelay: "0.4s" }} />
                  </>
                )}
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Zone saisie premium : elle ne recouvre jamais les messages. */}
        <div className="chat-composer" style={{
          flexShrink: 0,
          margin: "0 2% 6px",
        }}>
          <style>{`
            @keyframes chat-pulse-ring {
              0% { transform: scale(1); opacity: 0.9; }
              70% { transform: scale(1.55); opacity: 0; }
              100% { transform: scale(1.55); opacity: 0; }
            }
            .chat-input-bar {
              display: flex;
              align-items: center;
              min-height: 64px;
              gap: 8px;
              background: color-mix(in srgb, var(--input-bg) 85%, transparent);
              border: 1px solid rgba(255,255,255,0.1);
              border-radius: 28px;
              padding: 8px 10px 8px 24px;
              box-shadow: 0 8px 32px rgba(0,0,0,0.28), 0 1px 0 rgba(255,255,255,0.04) inset;
              backdrop-filter: blur(16px);
              transition: border-color 0.2s ease, box-shadow 0.2s ease;
            }
            .chat-input-bar:focus-within {
              border-color: rgba(138,180,248,0.35);
              box-shadow: 0 8px 40px rgba(0,0,0,0.3), 0 0 0 3px rgba(138,180,248,0.08), 0 1px 0 rgba(255,255,255,0.05) inset;
            }
            .chat-source-chip {
              display: inline-flex;
              align-items: center;
              gap: 5px;
              min-height: 40px;
              padding: 0 12px;
              border-radius: 20px;
              border: 1px solid rgba(138,180,248,0.25);
              background: rgba(138,180,248,0.1);
              color: #8ab4f8;
              font-size: 11.5px;
              font-weight: 600;
              flex-shrink: 0;
              justify-content: center;
              letter-spacing: 0.01em;
              transition: background 0.2s, border-color 0.2s;
            }
            .chat-source-chip:hover {
              background: rgba(138,180,248,0.16);
              border-color: rgba(138,180,248,0.45);
            }
            .chat-btn-mic {
              width: 42px; height: 42px;
              border-radius: 50%;
              border: 1px solid var(--border-color);
              background: color-mix(in srgb, var(--bg-panel) 80%, transparent);
              color: var(--text-muted);
              display: flex; align-items: center; justify-content: center;
              cursor: pointer;
              flex-shrink: 0;
              position: relative;
              transition: background 0.2s, color 0.2s, border-color 0.2s, transform 0.15s;
            }
            .chat-btn-mic:hover:not(:disabled) {
              color: var(--text-main);
              background: var(--bubble-ai);
              border-color: rgba(255,255,255,0.15);
              transform: scale(1.06);
            }
            .chat-btn-mic--recording {
              background: rgba(239, 68, 68, 0.15) !important;
              border-color: rgba(239, 68, 68, 0.4) !important;
              color: #ef4444 !important;
            }
            .chat-btn-mic--recording::before {
              content: '';
              position: absolute;
              inset: 0;
              border-radius: 50%;
              background: rgba(239,68,68,0.35);
              animation: chat-pulse-ring 1.4s ease-out infinite;
            }
            .chat-btn-send {
              width: 42px; height: 42px;
              border-radius: 50%;
              border: none;
              background: linear-gradient(135deg, #8ab4f8, #a78bfa);
              color: #fff;
              display: flex; align-items: center; justify-content: center;
              cursor: pointer;
              flex-shrink: 0;
              box-shadow: 0 4px 14px rgba(138,180,248,0.35);
              transition: transform 0.15s, box-shadow 0.15s, opacity 0.2s;
            }
            .chat-btn-send:hover:not(:disabled) {
              transform: scale(1.08) translateY(-1px);
              box-shadow: 0 6px 20px rgba(138,180,248,0.5);
            }
            .chat-btn-send:active:not(:disabled) {
              transform: scale(0.95);
            }
            .chat-btn-send:disabled {
              background: var(--bubble-ai);
              color: var(--text-dim);
              box-shadow: none;
              cursor: not-allowed;
            }
          `}</style>
          <div className="chat-input-bar">
            <PlaceholdersAndVanishInput
              placeholders={CHAT_PLACEHOLDERS}
              value={input}
              onChange={e => setInput(e.target.value)}
              onSubmit={() => {
                const userMsg = input.trim();
                if (!userMsg || !sessionId || loading) return;
                setInput("");
                sendMessage(userMsg);
              }}
              submitDisabled={!sessionId || loading}
            />

            {/* Source chip */}
            <span className="chat-source-chip">
              <svg width="11" height="11" fill="currentColor" viewBox="0 0 24 24">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Z" />
                <path d="M14 2v6h6" />
              </svg>
              {sourceCount} source{sourceCount !== 1 ? "s" : ""}
            </span>

            {/* Mic button */}
            <button
              onClick={toggleRecording}
              disabled={loading}
              title={isRecording ? "Arrêter l'enregistrement" : "Saisie vocale"}
              aria-label={isRecording ? "Arrêter l’enregistrement vocal" : "Démarrer la saisie vocale"}
              className={`chat-btn-mic${isRecording ? " chat-btn-mic--recording" : ""}`}
            >
              {isRecording ? (
                <svg width="16" height="16" fill="currentColor" viewBox="0 0 24 24">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              ) : (
                <svg width="17" height="17" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24">
                  <path d="M8 22h8" /><path d="M12 14a3 3 0 0 1-3-3V5a3 3 0 1 1 6 0v6a3 3 0 0 1-3 3Z" />
                  <path d="M19 11a7 7 0 1 1-14 0" /><path d="M12 18v4" />
                </svg>
              )}
            </button>

            {/* Send button */}
            <span className="has-kbd-hint">
              <button
                onClick={send}
                disabled={!input.trim() || !sessionId || loading}
                className="chat-btn-send"
                aria-label="Envoyer le message"
              >
                <svg width="18" height="18" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M22 2 11 13" /><path d="m22 2-7 20-4-9-9-4 20-7Z" />
                </svg>
              </button>
              <span className="kbd-hint" aria-hidden="true">Entrée</span>
            </span>
          </div>
        </div>

      </div>


      {/* Chat Settings Modal */}
      <ChatSettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />

      {/* Lightbox pour les images */}
      <ImageLightbox src={lightboxImage} onClose={() => setLightboxImage(null)} />

      {/* Modal pour afficher l'extrait de la source */}
      {selectedSource && (
        <Modal
          isOpen={!!selectedSource}
          onClose={() => setSelectedSource(null)}
          title={`Extrait du document — Page ${selectedSource.page}`}
          maxWidth="600px"
        >
          <div style={{
            background: "var(--bubble-ai)",
            border: "1px solid var(--border-color)",
            borderRadius: "12px",
            padding: "16px 20px",
            fontSize: "13.5px",
            lineHeight: "1.65",
            color: "var(--text-main)",
            whiteSpace: "pre-wrap",
            maxHeight: "60vh",
            overflowY: "auto",
          }}>
            {selectedSource.text}
          </div>
        </Modal>
      )}
    </div>
  );
}
