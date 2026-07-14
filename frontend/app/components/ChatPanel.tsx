"use client";
import { useState, useRef, useEffect } from "react";
import TextType from "./TextType";
import ChatSettingsModal from "./ChatSettingsModal";
import ModelsModal from "./ModelsModal";
import ChatMoreMenu from "./ChatMoreMenu";
import ImageLightbox from "./ImageLightbox";
import { ImageZoom, Image } from "./ImageZoom";
import Modal from "./Modal";
import { SmoothInput } from "./SmoothInput";
 
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
}
 
// Helper pour parser le gras et le code inline
function renderInlineMarkdown(text: string): React.ReactNode[] {
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

// ── Rendu markdown amélioré ──────────────────────────────────
function renderMarkdown(text: string, onPropositionClick?: (text: string) => void): React.ReactNode[] {
  const lines = text.split("\n");
  let inPropositions = false;

  return lines.map((line, i) => {
    const cleanLine = line.trim();

    // 1. Détection des titres (headers)
    if (cleanLine.startsWith("#")) {
      const match = cleanLine.match(/^(#{1,6})\s+(.*)$/);
      if (match) {
        const level = match[1].length; // 1 à 6
        const content = match[2];
        const HeaderTag = `h${level}` as any;

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

        const style: React.CSSProperties = {
          margin: level === 1 ? "18px 0 10px" : level === 2 ? "16px 0 8px" : "12px 0 6px",
          fontWeight: 600,
          fontSize: level === 1 ? "18px" : level === 2 ? "16px" : level === 3 ? "14px" : "13px",
          color: "var(--text-main)",
          lineHeight: 1.4,
        };

        return <HeaderTag key={i} style={style}>{renderInlineMarkdown(content)}</HeaderTag>;
      }
    }

    // 2. Détection des listes à puces (bullet points) ou numérotées
    const isBullet = cleanLine.startsWith("- ") || cleanLine.startsWith("* ") || cleanLine.startsWith("• ");
    const numMatch = cleanLine.match(/^(\d+)\.\s+(.*)$/);

    if (isBullet || numMatch) {
      let content = "";
      let prefix = "";
      if (isBullet) {
        content = cleanLine.substring(2);
        prefix = "•";
      } else {
        prefix = numMatch![1] + ".";
        content = numMatch![2];
      }

      if (inPropositions && onPropositionClick) {
        // En mode proposition, on rend une bulle cliquable
        return (
          <div
            key={i}
            onClick={() => onPropositionClick(content.replace(/\*\*/g, ""))} // Enlève le gras pour l'input
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
            {renderInlineMarkdown(content)}
          </div>
        );
      }

      return (
        <div key={i} style={{ display: "flex", gap: "8px", margin: "6px 0 6px 12px", alignItems: "flex-start" }}>
          <span style={{ color: "var(--accent-color)", fontWeight: numMatch ? "bold" : "normal", fontSize: numMatch ? "13px" : "inherit", marginTop: numMatch ? "0" : "1px" }}>{prefix}</span>
          <span style={{ flex: 1 }}>{renderInlineMarkdown(content)}</span>
        </div>
      );
    }

    // 4. Paragraphe classique ou ligne vide
    if (cleanLine === "") {
      return <div key={i} style={{ height: "8px" }} />;
    }

    return (
      <p key={i} style={{ margin: "4px 0" }}>
        {renderInlineMarkdown(line)}
      </p>
    );
  });
}
// ─────────────────────────────────────────────────────────────
 
export default function ChatPanel({ sessionId, sourceCount, initialMessage, selectedModel }: Props) {
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
  const [isModelsOpen, setIsModelsOpen] = useState(false);
  const [isMoreMenuOpen, setIsMoreMenuOpen] = useState(false);
  const moreMenuRef = useRef<HTMLButtonElement>(null);

  const [isRecording, setIsRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

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
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);
 
  // Ajout du message initial une seule fois par session
  useEffect(() => {
    if (initialMessage && !initialMessageAdded.current) {
      initialMessageAdded.current = true;
      setMessages([initialMessage]);
    }
  }, [initialMessage]);
 
  // Charger l'historique ou reset quand sessionId change (nouvelle session)
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setTypingDone(new Set());
      initialMessageAdded.current = false;
    } else {
      const fetchHistory = async () => {
        try {
          setLoading(true);
          const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
          const res = await fetch(`${apiUrl}/api/sessions/${sessionId}`);
          if (!res.ok) throw new Error("Erreur serveur");
          const data = await res.json();
          
          if (data && data.messages) {
            setMessages(data.messages);
            
            // Marquer les anciens messages comme tapés pour éviter l'animation d'écriture
            const doneSet = new Set<number>();
            data.messages.forEach((_: any, idx: number) => doneSet.add(idx));
            setTypingDone(doneSet);
          }
        } catch (err) {
          console.error("Erreur lors du chargement de l'historique:", err);
        } finally {
          setLoading(false);
        }
      };
      fetchHistory();
    }
  }, [sessionId]);
 
  const sendMessage = async (text: string) => {
    if (!text || !sessionId || loading) return;
    setMessages(m => [...m, { role: "user", text }]);
    setLoading(true);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
      const res = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text, model: selectedModel }),
      });
      const data = await res.json();
      setMessages(m => [...m, {
        role: "assistant",
        text: data.response,
        images: data.images || [],
        sources: data.sources || [],
      }]);
    } catch {
      setMessages(m => [...m, { role: "assistant", text: "Erreur de connexion au serveur." }]);
    }
    setLoading(false);
  };

  const send = async () => {
    const userMsg = input.trim();
    if (!userMsg) return;
    setInput("");
    await sendMessage(userMsg);
  };
 
  return (
    <div style={{
      flex: 1,
      height: "98%",
      marginTop: "10px",
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
        <div style={{ display: "flex", gap: "4px" }}>
          <button
            onClick={() => setIsModelsOpen(true)}
            style={{
              width: "36px", height: "36px", borderRadius: "50%",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "var(--text-muted)", fontSize: "16px", cursor: "pointer",
              border: "none", background: "transparent",
              transition: "background 0.2s",
            }}
            onMouseEnter={e => e.currentTarget.style.background = "var(--bubble-ai)"}
            onMouseLeave={e => e.currentTarget.style.background = "transparent"}
            title="Modèles entraînés"
          >
            🚀
          </button>
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
            ⚙
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
            ⋮
          </button>
        </div>
 
        {/* More Menu Dropdown Overlay */}
        <ChatMoreMenu
          isOpen={isMoreMenuOpen}
          onClose={() => setIsMoreMenuOpen(false)}
          anchorRef={moreMenuRef}
          messages={messages}
          onClearChat={clearChat}
        />
      </div>
 
      {/* Zone messages + input flottant */}
      <div style={{ flex: 1, position: "relative", display: "flex", flexDirection: "column", overflow: "hidden" }}>
 
        {/* Messages */}
        <div style={{ flex: 1, overflowY: "auto", padding: "24px", paddingBottom: "130px" }}>
 
          {messages.length === 0 && (
            <div style={{ textAlign: "center", color: "var(--text-dim)", fontSize: "14px", marginTop: "60px" }}>
              Chargez une source et posez votre première question.
            </div>
          )}
 
          {messages.map((msg, i) => (
            <div key={i} style={{
              display: "flex",
              justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
              marginBottom: "22px",
            }}>
              {msg.role === "assistant" && (
                <div style={{
                  width: "32px", height: "32px", borderRadius: "50%",
                  background: "linear-gradient(135deg,#8ab4f8,#c58af9)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: "14px", flexShrink: 0, marginRight: "12px", marginTop: "2px",
                }}>✦</div>
              )}
              <div style={{
                maxWidth: "75%",
                fontSize: "14px",
                lineHeight: 1.7,
                color: "var(--text-main)",
                padding: "14px 18px",
                borderRadius: msg.role === "user" ? "18px 0 18px 18px" : "0 18px 18px 18px",
                background: msg.role === "user" ? "var(--bubble-user)" : "var(--bubble-ai)",
                border: `1px solid ${msg.role === "user" ? "rgba(138,180,248,0.2)" : "var(--border-muted)"}`,
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
                                📄 Page {src.page}
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
            <div style={{ display: "flex", marginBottom: "22px" }}>
              <div style={{
                width: "32px", height: "32px", borderRadius: "50%",
                background: "linear-gradient(135deg,#8ab4f8,#c58af9)",
                display: "flex", alignItems: "center", justifyContent: "center",
                marginRight: "12px", flexShrink: 0,
              }}>✦</div>
              <div style={{
                padding: "14px 18px",
                background: "var(--bubble-ai)",
                border: "1px solid var(--border-muted)",
                borderRadius: "0 18px 18px 18px",
                color: "var(--text-muted)", fontSize: "14px",
              }}>
                Analyse en cours...
              </div>
            </div>
          )}
 
          <div ref={bottomRef} />
        </div>
 
        {/* Input flottant */}
        <div style={{
          position: "absolute",
          bottom: "16px",
          left: "5%",
          right: "5%",
        }}>
          <div style={{
            display: "flex",
            alignItems: "flex-end",
            gap: "12px",
            background: "var(--input-bg)",
            border: "1px solid var(--border-color)",
            borderRadius: "24px",
            padding: "12px 16px",
            boxShadow: "0 4px 24px rgba(0,0,0,0.15)",
          }}>
            <SmoothInput
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Commencez à écrire..."
              wrapperClassName="flex-1 [&>div]:focus-within:outline-none"
              className="text-sm placeholder:text-[var(--text-muted)]"
              style={{
                background: "transparent",
                color: "var(--text-main)",
              }}
            />
            <span style={{
              fontSize: "12px", color: "var(--text-muted)",
              padding: "4px 10px",
              background: "var(--bubble-ai)",
              borderRadius: "12px",
              flexShrink: 0,
              alignSelf: "flex-end",
              marginBottom: "2px",
            }}>
              {sourceCount} source{sourceCount !== 1 ? "s" : ""}
            </span>
            <button
              onClick={toggleRecording}
              disabled={loading}
              title={isRecording ? "Arrêter l'enregistrement" : "Saisie vocale"}
              style={{
                width: "36px", height: "36px", borderRadius: "50%",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: "18px", flexShrink: 0,
                cursor: loading ? "not-allowed" : "pointer",
                background: isRecording ? "rgba(234, 67, 53, 0.15)" : "transparent",
                color: isRecording ? "#ea4335" : "var(--text-muted)",
                border: "none", transition: "all .2s",
                position: "relative",
              }}
              onMouseEnter={e => { if (!isRecording && !loading) e.currentTarget.style.background = "var(--bubble-ai)"; }}
              onMouseLeave={e => { if (!isRecording && !loading) e.currentTarget.style.background = "transparent"; }}
            >
              {isRecording ? (
                <svg width="20" height="20" fill="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
              ) : (
                <svg width="20" height="20" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                  <path d="M8 22h8"></path>
                  <path d="M12 14a3 3 0 0 1-3-3V5a3 3 0 1 1 6 0v6a3 3 0 0 1-3 3Z"></path>
                  <path d="M19 11a7 7 0 1 1-14 0"></path>
                  <path d="M12 18v4"></path>
                </svg>
              )}
            </button>
            <button
              onClick={send}
              disabled={!input.trim() || !sessionId || loading}
              style={{
                width: "36px", height: "36px", borderRadius: "50%",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: "18px", flexShrink: 0,
                cursor: input.trim() && sessionId ? "pointer" : "not-allowed",
                background: input.trim() && sessionId ? "var(--accent-color)" : "var(--bubble-ai)",
                color: input.trim() && sessionId ? "var(--bg-app)" : "var(--text-dim)",
                border: "none", transition: "all .2s",
              }}
            >→</button>
          </div>
        </div>
 
      </div>
 
      {/* Chat Settings Modal */}
      <ChatSettingsModal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} />

      {/* Models Modal */}
      <ModelsModal isOpen={isModelsOpen} onClose={() => setIsModelsOpen(false)} sessionId={sessionId} />
 
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