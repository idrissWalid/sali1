"use client";
import { useState, useRef, useEffect } from "react";
import type { CSSProperties, JSX, ReactNode } from "react";
import TextType from "./TextType";
import ChatSettingsModal from "./ChatSettingsModal";
import ChatMoreMenu from "./ChatMoreMenu";
import ImageLightbox from "./ImageLightbox";
import { ImageZoom, Image } from "./ImageZoom";
import Modal from "./Modal";
import { PlaceholdersAndVanishInput } from "./PlaceholdersAndVanishInput";
import WelcomePanel from "./WelcomePanel";
import { FileText, MoreVertical, Settings2 } from "lucide-react";

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
}

// Helper pour parser le gras et le code inline
function renderInlineMarkdown(text: string): ReactNode[] {
  const parts = text.split(/(\*\*.*?\*\*|`.*?`)/g);
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
          fontFamily: "'Roboto Mono', monospace",
        }}>
          {part.slice(1, -1)}
        </code>
      );
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
function renderMarkdown(text: string, onPropositionClick?: (text: string) => void): ReactNode[] {
  const lines = text.split("\n");
  let inPropositions = false;
  const nodes: ReactNode[] = [];

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
        nodes.push(renderTable(headerCells, alignCells, rows, `table-${i}`));
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

      nodes.push(<HeaderTag key={i} style={style}>{renderInlineMarkdown(content)}</HeaderTag>);
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
        nodes.push(
          <div
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
            {renderInlineMarkdown(listContent)}
          </div>
        );
        continue;
      }

      nodes.push(
        <div key={i} style={{ display: "flex", gap: "8px", margin: "6px 0 6px 12px", alignItems: "flex-start" }}>
          <span style={{ color: "var(--accent-color)", fontWeight: numMatch ? "bold" : "normal", fontSize: numMatch ? "13px" : "inherit", marginTop: numMatch ? "0" : "1px" }}>{prefix}</span>
          <span style={{ flex: 1 }}>{renderInlineMarkdown(listContent)}</span>
        </div>
      );
      continue;
    }

    // 4. Paragraphe classique ou ligne vide
    if (cleanLine === "") {
      nodes.push(<div key={i} style={{ height: "8px" }} />);
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

    nodes.push(
      <p key={i} style={{ margin: "4px 0" }}>
        {renderInlineMarkdown(line)}
      </p>
    );
  }

  return nodes;
}
// ─────────────────────────────────────────────────────────────

export default function ChatPanel({ sessionId, sourceCount, initialMessage, selectedModel, onUploadClick, onAssistantMessage }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const latestInput = useRef("");

  useEffect(() => {
    latestInput.current = input;
  }, [input]);
  const [loading, setLoading] = useState(false);
  const [typingDone, setTypingDone] = useState<Set<number>>(new Set());
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
          const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
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
        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
        const res = await fetch(`${apiUrl}/api/sessions/${sessionId}`);
        if (!res.ok) throw new Error("Erreur serveur");
        const data = await res.json();

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
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const selected = selectedModel?.trim();
      const res = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: text,
          ...(selected ? { model: selected } : {}),
        }),
        signal: controller.signal,
      });
      if (!res.ok) {
        const error = await res.text();
        throw new Error(error || `Erreur serveur (${res.status})`);
      }
      const data = await res.json();
      const textResponse = data.response;
      setMessages(m => [...m, {
        role: "assistant",
        text: textResponse,
        images: data.images || [],
        sources: data.sources || [],
      }]);
      onAssistantMessage?.(textResponse);
    } catch (err: any) {
      if (err && err.name === 'AbortError') {
        setMessages(m => [...m, { role: "assistant", text: "Réponse interrompue." }]);
      } else {
        setMessages(m => [...m, { role: "assistant", text: "Erreur de connexion au serveur." }]);
      }
    } finally {
      setLoading(false);
      abortControllerRef.current = null;
    }
  };

  const send = async () => {
    const userMsg = input.trim();
    if (!userMsg) return;
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
    <div style={{
      flex: 1,
      height: "100%",
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
        <span style={{ fontFamily: "'Google Sans',sans-serif", fontSize: "16px", fontWeight: 500, color: "var(--text-main)" }}>
          Discussion
        </span>

        <div style={{ display: "flex", gap: "8px" }}>
          {loading && (
            <button
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
      <div style={{ flex: 1, position: "relative", display: "flex", flexDirection: "column", overflow: "hidden" }}>

        {/* Messages */}
        <div
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

          {messages.map((msg, i) => (
            <div key={i} style={{
              display: "flex",
              justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
              marginBottom: "24px",
              animation: "msgFadeIn 0.25s ease-out both",
            }}>
              {msg.role === "assistant" && (
                <div style={{
                  width: "30px", height: "30px", borderRadius: "50%",
                  background: "linear-gradient(135deg,#8ab4f8,#a78bfa)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: "13px", flexShrink: 0, marginRight: "10px", marginTop: "4px",
                  boxShadow: "0 2px 10px rgba(138,180,248,0.3)",
                }}></div>
              )}
              <div style={{
                maxWidth: "75%",
                fontSize: "14px",
                lineHeight: 1.75,
                color: "var(--text-main)",
                padding: "13px 17px",
                borderRadius: msg.role === "user" ? "20px 4px 20px 20px" : "4px 20px 20px 20px",
                background: msg.role === "user"
                  ? "linear-gradient(135deg, rgba(138,180,248,0.18), rgba(167,139,250,0.12))"
                  : "var(--bubble-ai)",
                border: `1px solid ${msg.role === "user" ? "rgba(138,180,248,0.28)" : "var(--border-muted)"}`,
                boxShadow: msg.role === "user" ? "0 2px 12px rgba(138,180,248,0.1)" : "none",
              }}>
                {msg.role === "assistant" ? (
                  typingDone.has(i) ? (
                    // Typing terminé → rendu markdown
                    <div>
                      {renderMarkdown(msg.text, sendMessage)}
                      {msg.isSummary && (
                        <button
                          onClick={() => window.open(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"}/api/dashboard/${sessionId}`, "_blank")}
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
                      renderText={(text) => renderMarkdown(text, sendMessage)}
                      onComplete={() => {
                        setTypingDone(prev => new Set([...prev, i]));
                      }}
                    />
                  )
                ) : (
                  msg.text
                )}

                {/* Images générées par la sandbox */}
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
              </div>
            </div>
          ))}

          {loading && (
            <div style={{ display: "flex", marginBottom: "24px", animation: "msgFadeIn 0.25s ease-out both" }}>
              <div style={{
                width: "30px", height: "30px", borderRadius: "50%",
                background: "linear-gradient(135deg,#8ab4f8,#a78bfa)",
                display: "flex", alignItems: "center", justifyContent: "center",
                marginRight: "10px", flexShrink: 0,
                boxShadow: "0 2px 10px rgba(138,180,248,0.3)",
              }}></div>
              <div style={{
                padding: "14px 18px",
                background: "var(--bubble-ai)",
                border: "1px solid var(--border-muted)",
                borderRadius: "4px 20px 20px 20px",
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
                `}</style>
                <span className="chat-dot" style={{ background: "#8ab4f8", animationDelay: "0s" }} />
                <span className="chat-dot" style={{ background: "#a78bfa", animationDelay: "0.2s" }} />
                <span className="chat-dot" style={{ background: "#c58af9", animationDelay: "0.4s" }} />
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Zone saisie premium : elle ne recouvre jamais les messages. */}
        <div style={{
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
              disabled={!sessionId || loading}
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
            <button
              onClick={send}
              disabled={!input.trim() || !sessionId || loading}
              className="chat-btn-send"
            >
              <svg width="18" height="18" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" viewBox="0 0 24 24">
                <path d="M22 2 11 13" /><path d="m22 2-7 20-4-9-9-4 20-7Z" />
              </svg>
            </button>
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
