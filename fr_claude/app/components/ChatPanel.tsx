"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  BarChart3,
  FileText,
  Mic,
  MoreVertical,
  Send,
  Settings2,
  Square,
  UploadCloud,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { getSession, sendChatMessage, transcribeAudio } from "../lib/api";
import type { ChatSource, Message, UploadProgressState } from "../lib/types";
import MarkdownMessage from "./MarkdownMessage";
import Modal from "./Modal";
import WelcomeScreen from "./WelcomeScreen";

interface Props {
  sessionId: string | null;
  sourceCount: number;
  initialMessage: Message | null;
  selectedModel?: string;
  uploadProgress?: UploadProgressState | null;
  onUploadClick?: () => void;
  onAssistantMessage?: (text: string) => void;
}

const UPLOAD_STEPS = [
  { step: 1, label: "Lecture" },
  { step: 2, label: "Analyse" },
  { step: 3, label: "IA" },
  { step: 4, label: "Finalisation" },
];
const STEP_PCT: Record<number, number> = { 1: 25, 2: 50, 3: 75, 4: 95 };

function UploadProgressCard({ progress }: { progress: UploadProgressState }) {
  const pct = STEP_PCT[progress.step] ?? 10;
  return (
    <div className="flex h-full flex-col items-center justify-center px-6">
      <motion.div
        initial={{ opacity: 0, y: 10, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.25, ease: "easeOut" }}
        className="w-full max-w-sm rounded-lg border p-6"
        style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)" }}
      >
        <div className="relative mx-auto mb-5 grid size-16 place-items-center">
          <span
            className="fc-spin-slow absolute inset-0 rounded-full"
            style={{
              background: `conic-gradient(var(--accent) 0deg, color-mix(in srgb, var(--accent) 25%, transparent) 200deg, transparent 360deg)`,
              WebkitMask: "radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px))",
              mask: "radial-gradient(farthest-side, transparent calc(100% - 3px), #000 calc(100% - 3px))",
            }}
          />
          <span
            className="fc-glow-pulse absolute inset-2 rounded-full"
            style={{ background: "color-mix(in srgb, var(--accent) 16%, transparent)" }}
          />
          <UploadCloud size={22} strokeWidth={1.6} style={{ color: "var(--accent)" }} className="relative" />
        </div>

        <div className="mb-1 truncate text-center text-[13px] font-semibold" style={{ color: "var(--text-main)" }}>
          {progress.fileName}
        </div>
        <div
          key={progress.message}
          className="fc-fade-in mb-5 min-h-[18px] text-center text-[12.5px]"
          style={{ color: "var(--text-muted)" }}
        >
          {progress.message}
        </div>

        <div className="mb-5 flex items-center">
          {UPLOAD_STEPS.map((s, i) => {
            const status = progress.step === s.step ? "active" : progress.step < s.step ? "inactive" : "complete";
            return (
              <div key={s.step} className="flex flex-1 items-center">
                <div className="flex flex-col items-center gap-1.5">
                  <motion.div
                    animate={status}
                    initial={false}
                    variants={{
                      inactive: { backgroundColor: "var(--border-muted)", borderColor: "var(--border-color)" },
                      active: { backgroundColor: "var(--accent-soft)", borderColor: "var(--accent)" },
                      complete: { backgroundColor: "var(--accent)", borderColor: "var(--accent)" },
                    }}
                    transition={{ duration: 0.3 }}
                    className="grid size-6 shrink-0 place-items-center rounded-full border"
                    style={{ color: status === "complete" ? "var(--accent-contrast)" : status === "active" ? "var(--accent)" : "var(--text-dim)" }}
                  >
                    {status === "complete" ? (
                      <StepCheckIcon />
                    ) : status === "active" ? (
                      <span className="size-1.5 rounded-full" style={{ background: "var(--accent)" }} />
                    ) : (
                      <span className="text-[10px] font-bold">{s.step}</span>
                    )}
                  </motion.div>
                  <span
                    className="text-[9.5px] font-medium uppercase tracking-wide"
                    style={{ color: status === "active" ? "var(--accent)" : "var(--text-dim)" }}
                  >
                    {s.label}
                  </span>
                </div>
                {i < UPLOAD_STEPS.length - 1 && (
                  <div className="mx-1 h-[2px] flex-1 -translate-y-2.5 overflow-hidden rounded-full" style={{ background: "var(--border-color)" }}>
                    <motion.div
                      className="h-full rounded-full"
                      style={{ background: "var(--accent)" }}
                      initial={false}
                      animate={{ width: progress.step > s.step ? "100%" : "0%" }}
                      transition={{ duration: 0.4 }}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="relative h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--border-muted)" }}>
          <motion.div
            className="fc-shimmer relative h-full overflow-hidden rounded-full"
            style={{ background: "var(--accent)" }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.4, ease: "easeOut" }}
          />
        </div>
        <div className="mt-2 text-right text-[11px] font-semibold" style={{ color: "var(--accent)" }}>
          {pct}%
        </div>
      </motion.div>
    </div>
  );
}

function StepCheckIcon() {
  return (
    <svg width={12} height={12} fill="none" stroke="var(--accent-contrast)" strokeWidth={2} viewBox="0 0 24 24">
      <motion.path
        initial={{ pathLength: 0 }}
        animate={{ pathLength: 1 }}
        transition={{ delay: 0.1, type: "tween", ease: "easeOut", duration: 0.3 }}
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M5 13l4 4L19 7"
      />
    </svg>
  );
}

const PLACEHOLDERS = [
  "Posez votre question sur vos données...",
  "Quelles sont les tendances principales ?",
  "Résume ce document en 3 points clés.",
  "Compare les colonnes A et B...",
  "Génère un graphique de la distribution.",
  "Quelles anomalies détectes-tu ?",
];

function TypingText({ text, speed = 8, onDone, onProposition, sources, onSourceClick }: { text: string; speed?: number; onDone: () => void; onProposition?: (t: string) => void; sources?: ChatSource[]; onSourceClick?: (src: ChatSource) => void }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    setShown(0);
    if (!text) {
      onDone();
      return;
    }
    let i = 0;
    const id = setInterval(() => {
      i += Math.max(1, Math.round(text.length / 220));
      setShown(Math.min(i, text.length));
      if (i >= text.length) {
        clearInterval(id);
        onDone();
      }
    }, speed);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text]);

  return (
    <span>
      <MarkdownMessage text={text.slice(0, shown)} onPropositionClick={onProposition} sources={sources} onSourceClick={onSourceClick} />
      {shown < text.length && <span className="fc-caret">▍</span>}
    </span>
  );
}

export default function ChatPanel({ sessionId, sourceCount, initialMessage, selectedModel, uploadProgress, onUploadClick, onAssistantMessage }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  const [loading, setLoading] = useState(false);
  const [typingDone, setTypingDone] = useState<Set<number>>(new Set());
  const [lightbox, setLightbox] = useState<string | null>(null);
  const [selectedSource, setSelectedSource] = useState<ChatSource | null>(null);
  const [isMoreOpen, setIsMoreOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [isScrolling, setIsScrolling] = useState(false);

  const bottomRef = useRef<HTMLDivElement>(null);
  const initialAdded = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const inputRef = useRef(input);
  const moreBtnRef = useRef<HTMLButtonElement>(null);
  const moreMenuRef = useRef<HTMLDivElement>(null);
  const scrollHideTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleMessagesScroll = () => {
    setIsScrolling(true);
    if (scrollHideTimeout.current) clearTimeout(scrollHideTimeout.current);
    scrollHideTimeout.current = setTimeout(() => setIsScrolling(false), 2000);
  };

  useEffect(() => {
    return () => {
      if (scrollHideTimeout.current) clearTimeout(scrollHideTimeout.current);
    };
  }, []);

  useEffect(() => {
    inputRef.current = input;
  }, [input]);

  useEffect(() => {
    const id = setInterval(() => setPlaceholderIdx((p) => (p + 1) % PLACEHOLDERS.length), 3200);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  useEffect(() => {
    if (initialMessage && !initialAdded.current) {
      initialAdded.current = true;
      setMessages([initialMessage]);
    }
  }, [initialMessage]);

  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setTypingDone(new Set());
      initialAdded.current = false;
      return;
    }
    (async () => {
      try {
        const data = await getSession(sessionId);
        if (data.messages?.length) {
          setMessages(data.messages);
          setTypingDone(new Set(data.messages.map((_, i) => i)));
        } else if (initialMessage) {
          setMessages([initialMessage]);
        }
      } catch (err) {
        console.error(err);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      if (
        isMoreOpen &&
        moreMenuRef.current &&
        !moreMenuRef.current.contains(e.target as Node) &&
        moreBtnRef.current &&
        !moreBtnRef.current.contains(e.target as Node)
      ) {
        setIsMoreOpen(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [isMoreOpen]);

  const sendMessage = async (text: string) => {
    if (!text || !sessionId || loading) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setLoading(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const data = await sendChatMessage(sessionId, text, selectedModel, controller.signal);
      setMessages((m) => [...m, { role: "assistant", text: data.response, images: data.images || [], sources: data.sources || [] }]);
      onAssistantMessage?.(data.response);
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setMessages((m) => [...m, { role: "assistant", text: "Réponse interrompue." }]);
      } else {
        setMessages((m) => [...m, { role: "assistant", text: "Erreur de connexion au serveur." }]);
      }
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  };

  const handleSubmit = () => {
    const text = input.trim();
    if (!text || !sessionId || loading) return;
    setInput("");
    sendMessage(text);
  };

  const toggleRecording = async () => {
    if (isRecording) {
      mediaRecorderRef.current?.stop();
      setIsRecording(false);
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        try {
          setLoading(true);
          const text = await transcribeAudio(blob);
          if (text) {
            const merged = inputRef.current.trim() ? `${inputRef.current} ${text}` : text;
            setInput("");
            await sendMessage(merged);
          } else {
            setLoading(false);
          }
        } catch (err) {
          console.error(err);
          alert("Erreur lors de la transcription vocale.");
          setLoading(false);
        }
        stream.getTracks().forEach((t) => t.stop());
      };
      recorder.start();
      setIsRecording(true);
    } catch (err) {
      console.error(err);
      alert("Impossible d'accéder au microphone.");
    }
  };

  const exportMarkdown = () => {
    if (messages.length === 0) return alert("Aucun message à exporter !");
    const md = messages.map((m) => `### ${m.role === "user" ? "Utilisateur" : "Assistant IA"}\n\n${m.text}\n\n---\n`).join("\n");
    const blob = new Blob([`# Historique de Discussion\n\n${md}`], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "discussion_analyse.md";
    a.click();
    URL.revokeObjectURL(url);
    setIsMoreOpen(false);
  };

  const exportHTML = () => {
    if (messages.length === 0) return alert("Aucun message à exporter !");
    const rows = messages
      .map((m) => {
        const isUser = m.role === "user";
        return `<div style="display:flex;justify-content:${isUser ? "flex-end" : "flex-start"};margin-bottom:20px;"><div style="max-width:70%;padding:14px 18px;border-radius:6px;background:${isUser ? "#f4e9e0" : "#f1f3f4"};font-family:sans-serif;font-size:14px;line-height:1.6;"><strong style="display:block;margin-bottom:6px;font-size:12px;opacity:.7;">${isUser ? "Utilisateur" : "Assistant IA"}</strong><div>${m.text.replace(/\n/g, "<br>")}</div></div></div>`;
      })
      .join("");
    const html = `<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>Discussion exportée</title></head><body style="background:#f8f9fa;padding:40px;font-family:sans-serif;"><div style="max-width:800px;margin:0 auto;background:#fff;padding:30px;border-radius:8px;"><h1>Historique de Discussion</h1>${rows}</div></body></html>`;
    const blob = new Blob([html], { type: "text/html" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "discussion_analyse.html";
    a.click();
    URL.revokeObjectURL(url);
    setIsMoreOpen(false);
  };

  const clearChat = () => {
    if (!confirm("Voulez-vous vraiment effacer tous les messages ?")) return;
    setMessages([]);
    setTypingDone(new Set());
    setIsMoreOpen(false);
  };

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border" style={{ background: "var(--bg-chat)", borderColor: "var(--border-color)" }}>
      <div className="flex shrink-0 items-center justify-between border-b px-6 py-3.5" style={{ borderColor: "var(--border-muted)" }}>
        <span className="font-serif text-[16px] font-medium" style={{ color: "var(--text-main)" }}>Discussion</span>
        <div className="flex items-center gap-1">
          {loading && (
            <button
              onClick={() => {
                abortRef.current?.abort();
                setLoading(false);
              }}
              title="Interrompre"
              className="grid size-8 place-items-center rounded-md transition-colors hover:bg-[var(--bubble-ai)]"
              style={{ color: "var(--text-muted)" }}
            >
              <Square size={14} />
            </button>
          )}
          <button
            onClick={() => setIsSettingsOpen(true)}
            className="grid size-8 place-items-center rounded-md transition-colors hover:bg-[var(--bubble-ai)]"
            style={{ color: "var(--text-muted)" }}
          >
            <Settings2 size={15} strokeWidth={1.6} />
          </button>
          <button
            ref={moreBtnRef}
            onClick={() => setIsMoreOpen((v) => !v)}
            className="grid size-8 place-items-center rounded-md transition-colors hover:bg-[var(--bubble-ai)]"
            style={{ color: "var(--text-muted)" }}
          >
            <MoreVertical size={16} strokeWidth={1.6} />
          </button>
        </div>
      </div>

      <AnimatePresence>
        {isMoreOpen && (
          <motion.div
            ref={moreMenuRef}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="absolute right-6 top-14 z-50 flex w-52 flex-col gap-0.5 rounded-md border p-1.5 shadow-xl"
            style={{ background: "var(--bg-panel)", borderColor: "var(--border-color)" }}
          >
            {[
              { label: "Exporter en Markdown", action: exportMarkdown },
              { label: "Exporter en HTML", action: exportHTML },
              { label: "Vider la discussion", action: clearChat, danger: true },
            ].map((item) => (
              <button
                key={item.label}
                onClick={item.action}
                className="rounded px-3 py-2 text-left text-[13px] transition-colors hover:bg-[var(--bubble-ai)]"
                style={{ color: item.danger ? "var(--danger)" : "var(--text-main)" }}
              >
                {item.label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>

      <div className="relative flex flex-1 flex-col overflow-hidden">
        <div
          className={`fc-autoscroll flex-1 overflow-y-auto px-6 py-6 sm:px-10${isScrolling ? " is-scrolling" : ""}`}
          onScroll={handleMessagesScroll}
        >
          {uploadProgress?.active ? (
            <UploadProgressCard progress={uploadProgress} />
          ) : (
            <>
          {messages.length === 0 && sourceCount === 0 && <WelcomeScreen onUpload={() => onUploadClick?.()} />}
          {messages.length === 0 && sourceCount > 0 && (
            <div className="flex h-full items-center justify-center px-6 text-center text-[14px]" style={{ color: "var(--text-dim)" }}>
              Votre source est prête. Posez votre première question.
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className="mb-7 fc-fade-up">
              {msg.role === "user" && (
                <div
                  className="mb-1.5 text-[10.5px] font-medium uppercase tracking-wider"
                  style={{ color: "var(--text-dim)", textAlign: "right" }}
                >
                  Vous
                </div>
              )}

              {msg.role === "user" ? (
                <div
                  className="ml-auto max-w-[70%] rounded-md border px-4 py-3 text-[14px] leading-[1.7]"
                  style={{ color: "var(--text-main)", background: "var(--bubble-user)", borderColor: "var(--border-muted)" }}
                >
                  {msg.text}
                </div>
              ) : (
                <div className="max-w-[78%] text-[14px] leading-[1.75]" style={{ color: "var(--text-main)" }}>
                  {typingDone.has(i) ? (
                    <MarkdownMessage text={msg.text} onPropositionClick={sendMessage} section="content" sources={msg.sources} onSourceClick={setSelectedSource} />
                  ) : (
                    <TypingText text={msg.text || ""} onDone={() => setTypingDone((prev) => new Set([...prev, i]))} onProposition={sendMessage} sources={msg.sources} onSourceClick={setSelectedSource} />
                  )}

                  {msg.isSummary && typingDone.has(i) && sessionId && (
                    <button
                      onClick={() => window.open(`/dashboard/${sessionId}`, "_blank")}
                      className="mt-4 flex items-center gap-2 rounded-md border px-4 py-2 text-[13px] font-medium transition-colors hover:bg-[var(--bubble-ai)]"
                      style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
                    >
                      <BarChart3 size={15} /> Voir le Dashboard interactif
                    </button>
                  )}

                  {/* Graphiques générés par la sandbox — avant les suggestions */}
                  {msg.images && msg.images.length > 0 && (
                    <div className="mt-3 flex flex-col gap-2.5">
                      {msg.images.map((img, j) => (
                        <button key={j} onClick={() => setLightbox(`data:image/png;base64,${img}`)} className="overflow-hidden rounded-md border" style={{ borderColor: "var(--border-color)" }}>
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={`data:image/png;base64,${img}`} alt={`Visualisation ${j + 1}`} className="w-full" />
                        </button>
                      ))}
                    </div>
                  )}

                  {typingDone.has(i) && (
                    <MarkdownMessage text={msg.text} onPropositionClick={sendMessage} section="suggestions" />
                  )}

                  {msg.sources && msg.sources.length > 0 && (
                    <div className="mt-3.5 border-t pt-2.5" style={{ borderColor: "var(--border-muted)" }}>
                      <div className="mb-2 text-[10.5px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-muted)" }}>
                        Sources & Références
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {msg.sources.map((src, idx) => (
                          <button
                            key={idx}
                            onClick={() => setSelectedSource(src)}
                            className="flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12px] transition-colors hover:border-[var(--accent)]"
                            style={{ borderColor: "var(--border-color)", background: "var(--bg-panel)", color: "var(--text-main)" }}
                          >
                            <FileText size={12} strokeWidth={1.6} /> Page {src.page}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}

          {loading && (
            <div className="mb-7 fc-fade-up">
              <div className="flex items-center gap-1.5">
                <span className="fc-dot" style={{ background: "var(--accent)" }} />
                <span className="fc-dot" style={{ background: "var(--accent)", animationDelay: "0.2s" }} />
                <span className="fc-dot" style={{ background: "var(--accent)", animationDelay: "0.4s" }} />
              </div>
            </div>
          )}
            </>
          )}

          <div ref={bottomRef} />
        </div>

        <div className="mx-4 mb-3 shrink-0 sm:mx-8">
          <div
            className="flex min-h-14 items-center gap-2 rounded-md border px-3 py-2 transition-colors focus-within:border-[var(--accent)]"
            style={{ background: "var(--input-bg)", borderColor: "var(--border-color)" }}
          >
            <div className="relative flex h-10 min-w-0 flex-1 items-center">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleSubmit();
                  }
                }}
                disabled={!sessionId || loading}
                className="h-10 w-full bg-transparent text-[14.5px] outline-none"
                style={{ color: "var(--text-main)" }}
              />
              <div className="pointer-events-none absolute inset-0 flex h-10 items-center">
                <AnimatePresence mode="wait">
                  {!input && (
                    <motion.p
                      key={placeholderIdx}
                      initial={{ y: 4, opacity: 0 }}
                      animate={{ y: 0, opacity: 1 }}
                      exit={{ y: -6, opacity: 0 }}
                      transition={{ duration: 0.18 }}
                      className="w-full select-none truncate text-[14.5px]"
                      style={{ color: "var(--text-muted)" }}
                    >
                      {PLACEHOLDERS[placeholderIdx]}
                    </motion.p>
                  )}
                </AnimatePresence>
              </div>
            </div>

            <span
              className="hidden shrink-0 items-center rounded border px-2.5 py-1.5 text-[11px] font-medium sm:inline-flex"
              style={{ borderColor: "var(--border-color)", color: "var(--text-muted)" }}
            >
              {sourceCount} source{sourceCount !== 1 ? "s" : ""}
            </span>

            <button
              onClick={toggleRecording}
              disabled={loading}
              title={isRecording ? "Arrêter l'enregistrement" : "Saisie vocale"}
              className="relative grid size-9 shrink-0 place-items-center rounded-md border transition-colors"
              style={{
                borderColor: isRecording ? "var(--danger)" : "var(--border-color)",
                background: isRecording ? "color-mix(in srgb, var(--danger) 12%, transparent)" : "transparent",
                color: isRecording ? "var(--danger)" : "var(--text-muted)",
              }}
            >
              {isRecording && (
                <span className="absolute inset-0 rounded-md" style={{ background: "color-mix(in srgb, var(--danger) 25%, transparent)", animation: "fc-pulse-ring 1.4s ease-out infinite" }} />
              )}
              {isRecording ? <Square size={14} /> : <Mic size={15} strokeWidth={1.6} />}
            </button>

            <button
              onClick={handleSubmit}
              disabled={!input.trim() || !sessionId || loading}
              className="grid size-9 shrink-0 place-items-center rounded-md text-white transition-colors disabled:cursor-not-allowed disabled:opacity-40"
              style={{ background: "var(--accent)" }}
            >
              <Send size={15} strokeWidth={2} />
            </button>
          </div>
        </div>
      </div>

      <Modal isOpen={isSettingsOpen} onClose={() => setIsSettingsOpen(false)} title="Paramètres de discussion" maxWidth="440px">
        <ChatSettingsBody onClose={() => setIsSettingsOpen(false)} />
      </Modal>

      <AnimatePresence>
        {lightbox && (
          <motion.div
            className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/85 p-6"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setLightbox(null)}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={lightbox} alt="Aperçu" className="max-h-full max-w-full rounded-md" />
            <button className="absolute right-6 top-6 grid size-9 place-items-center rounded-md bg-white/10 text-white">
              <X size={17} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      <Modal isOpen={!!selectedSource} onClose={() => setSelectedSource(null)} title={`Extrait du document — Page ${selectedSource?.page ?? ""}`} maxWidth="600px">
        <div className="rounded-md border p-4 text-[13.5px] leading-relaxed" style={{ background: "var(--bubble-ai)", borderColor: "var(--border-color)", whiteSpace: "pre-wrap", maxHeight: "60vh", overflowY: "auto" }}>
          {selectedSource?.text}
        </div>
      </Modal>
    </div>
  );
}

function ChatSettingsBody({ onClose }: { onClose: () => void }) {
  const [typingSpeed, setTypingSpeed] = useState(40);
  const [systemPrompt, setSystemPrompt] = useState("Tu es un analyste de données expert. Réponds de façon concise et structure tes réponses.");
  const [autoScroll, setAutoScroll] = useState(true);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <label className="text-[12px] font-medium" style={{ color: "var(--text-muted)" }}>
            Vitesse de frappe de l&apos;IA ({typingSpeed} ms)
          </label>
        </div>
        <input type="range" min={10} max={100} step={5} value={typingSpeed} onChange={(e) => setTypingSpeed(parseInt(e.target.value))} className="w-full accent-[var(--accent)]" />
      </div>

      <div className="flex flex-col gap-1.5">
        <label className="text-[12px] font-medium" style={{ color: "var(--text-muted)" }}>Instructions système de l&apos;IA</label>
        <textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          rows={4}
          className="resize-none rounded-md border px-3.5 py-2.5 text-[13px] outline-none"
          style={{ borderColor: "var(--border-color)", background: "var(--bg-app)", color: "var(--text-main)" }}
        />
      </div>

      <div className="flex items-center justify-between">
        <div>
          <div className="text-[13px] font-medium" style={{ color: "var(--text-main)" }}>Défilement automatique</div>
          <div className="mt-0.5 text-[11px]" style={{ color: "var(--text-muted)" }}>Défiler vers le bas à la réception des messages</div>
        </div>
        <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} className="size-[18px] accent-[var(--accent)]" />
      </div>

      <div className="flex justify-end gap-3 border-t pt-4" style={{ borderColor: "var(--border-muted)" }}>
        <button onClick={onClose} className="rounded-md border px-4 py-2 text-[13px] font-medium" style={{ borderColor: "var(--border-color)", color: "var(--text-muted)" }}>
          Annuler
        </button>
        <button
          onClick={() => {
            alert("Paramètres de la discussion mis à jour !");
            onClose();
          }}
          className="rounded-md px-5 py-2 text-[13px] font-medium text-white"
          style={{ background: "var(--accent)" }}
        >
          Valider
        </button>
      </div>
    </div>
  );
}
