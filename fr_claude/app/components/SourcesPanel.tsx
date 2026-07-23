"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Check, FileText, Loader2, Search, Table2, Upload, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { streamUpload } from "../lib/api";
import type { SourceItem, UploadData, UploadProgressState } from "../lib/types";
import Modal from "./Modal";

interface Props {
  sources: SourceItem[];
  onUpload: (data: UploadData) => void;
  onRemove: (index: number) => void;
  selectedModel?: string;
  registerUploadHandler?: (handler: (() => void) | null) => void;
  onProgressChange?: (progress: UploadProgressState | null) => void;
}

const STEP_PCT: Record<number, number> = { 1: 25, 2: 50, 3: 75, 4: 95 };

export default function SourcesPanel({ sources, onUpload, onRemove, selectedModel, registerUploadHandler, onProgressChange }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [isUploadModalOpen, setIsUploadModalOpen] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [progress, setProgress] = useState<{ active: boolean; fileName: string; step: number; message: string }>({
    active: false,
    fileName: "",
    step: 0,
    message: "",
  });

  useEffect(() => {
    registerUploadHandler?.(() => setIsUploadModalOpen(true));
    return () => registerUploadHandler?.(null);
  }, [registerUploadHandler]);

  useEffect(() => {
    onProgressChange?.(progress.active ? progress : null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [progress]);

  const processFile = async (file: File) => {
    setProgress({ active: true, fileName: file.name, step: 1, message: "Lecture et détection du format du fichier..." });
    try {
      for await (const evt of streamUpload(file, selectedModel)) {
        if (evt.status === "processing") {
          setProgress({ active: true, fileName: file.name, step: evt.step ?? 1, message: evt.message ?? "" });
        } else if (evt.status === "error" || evt.status === "clarification_needed") {
          alert(evt.message || "Une erreur est survenue lors du traitement.");
          setProgress((p) => ({ ...p, active: false }));
          return;
        } else if (evt.status === "completed" && evt.data) {
          evt.data.filename = evt.data.filename || file.name;
          onUpload(evt.data);
          setProgress((p) => ({ ...p, active: false }));
          return;
        }
      }
    } catch (err) {
      console.error(err);
      alert("Erreur lors du chargement. Vérifiez que le backend est démarré.");
      setProgress((p) => ({ ...p, active: false }));
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleFileInput = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setIsUploadModalOpen(false);
    await processFile(f);
  };

  const filtered = query.trim()
    ? sources.filter((s) => s.name.toLowerCase().includes(query.trim().toLowerCase()))
    : sources;

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div
        className="mx-4 mt-3 mb-3 flex items-center gap-2 rounded-md border px-3 py-2"
        style={{ background: "transparent", borderColor: "var(--border-color)" }}
      >
        <Search size={15} strokeWidth={1.8} style={{ color: "var(--text-muted)" }} />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Rechercher une source"
          className="w-full bg-transparent text-[13px] outline-none"
          style={{ color: "var(--text-main)" }}
        />
      </div>

      {progress.active ? (
        <div
          className="mx-4 mb-3 flex flex-col gap-3 rounded-md border p-4"
          style={{ borderColor: "var(--accent)", background: "var(--bubble-user)" }}
        >
          <div className="flex items-center gap-2.5">
            <Loader2 size={17} className="animate-spin shrink-0" style={{ color: "var(--accent)" }} />
            <div className="flex-1 truncate text-[12px] font-semibold" style={{ color: "var(--text-main)" }}>
              {progress.fileName}
            </div>
            <span
              className="rounded px-2 py-0.5 text-[10px] font-bold"
              style={{ background: "var(--border-color)", color: "var(--accent)" }}
            >
              {STEP_PCT[progress.step] ?? 10}%
            </span>
          </div>
          <div className="min-h-[18px] text-[12.5px] font-medium fc-fade-in" key={progress.message} style={{ color: "var(--text-main)" }}>
            {progress.message}
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full" style={{ background: "var(--border-muted)" }}>
            <motion.div
              className="h-full rounded-full"
              style={{ background: "var(--accent)" }}
              animate={{ width: `${STEP_PCT[progress.step] ?? 10}%` }}
              transition={{ duration: 0.4, ease: "easeOut" }}
            />
          </div>
        </div>
      ) : (
        <button
          onClick={() => setIsUploadModalOpen(true)}
          className="mx-4 mb-3 flex items-center justify-center gap-2 rounded-md border py-2.5 text-[13px] font-medium transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
          style={{ borderColor: "var(--border-color)", color: "var(--text-muted)" }}
        >
          <Upload size={15} strokeWidth={1.8} /> Ajouter une source
        </button>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,.xlsx,.xls,.pdf,.docx"
        className="hidden"
        onChange={handleFileInput}
      />

      <div className="flex-1 overflow-y-auto px-2.5 pb-3">
        {filtered.length === 0 && (
          <div className="px-4 py-10 text-center text-[13px] leading-relaxed" style={{ color: "var(--text-dim)" }}>
            {sources.length === 0 ? (
              <>Aucune source chargée.<br />Ajoutez un fichier CSV, Excel ou PDF.</>
            ) : (
              "Aucun résultat pour cette recherche."
            )}
          </div>
        )}
        <AnimatePresence initial={false}>
          {filtered.map((src) => {
            const realIndex = sources.indexOf(src);
            return (
              <motion.div
                key={`${src.name}-${realIndex}`}
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="group flex items-center gap-3 rounded-md px-3 py-2.5 transition-colors hover:bg-[var(--bubble-ai)]"
              >
                <div className="grid size-8 shrink-0 place-items-center rounded-md border" style={{ borderColor: "var(--border-muted)" }}>
                  {src.type === "tabular" ? (
                    <Table2 size={15} style={{ color: "var(--accent)" }} />
                  ) : (
                    <FileText size={15} style={{ color: "var(--text-muted)" }} />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px]" style={{ color: "var(--text-main)" }}>{src.name}</div>
                  <div className="text-[11px]" style={{ color: "var(--text-muted)" }}>{src.meta}</div>
                </div>
                <Check size={15} strokeWidth={2} style={{ color: "var(--accent)" }} className="shrink-0" />
                <button
                  onClick={() => onRemove(realIndex)}
                  className="shrink-0 rounded p-1 opacity-0 transition-opacity group-hover:opacity-100 hover:text-[var(--danger)]"
                  style={{ color: "var(--text-dim)" }}
                >
                  <X size={15} strokeWidth={1.8} />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>

      <Modal isOpen={isUploadModalOpen} onClose={() => setIsUploadModalOpen(false)} title="Ajouter une source" maxWidth="480px">
        <div
          onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setIsDragging(false);
            const f = e.dataTransfer.files?.[0];
            if (f) {
              setIsUploadModalOpen(false);
              processFile(f);
            }
          }}
          onClick={() => fileInputRef.current?.click()}
          className="flex cursor-pointer flex-col items-center gap-4 rounded-md border-2 border-dashed px-6 py-12 text-center transition-colors"
          style={{
            borderColor: isDragging ? "var(--accent)" : "var(--border-color)",
            background: isDragging ? "var(--bubble-ai)" : "transparent",
          }}
        >
          <div className="grid size-14 place-items-center rounded-md border" style={{ borderColor: "var(--border-color)", color: "var(--accent)" }}>
            <Upload size={28} strokeWidth={1.7} />
          </div>
          <div>
            <div className="mb-1.5 text-[15px] font-semibold" style={{ color: "var(--text-main)" }}>
              Glissez et déposez votre fichier ici
            </div>
            <div className="text-[13px]" style={{ color: "var(--text-muted)" }}>
              ou <span style={{ color: "var(--accent)", fontWeight: 500 }}>cliquez pour parcourir</span>
            </div>
          </div>
          <div className="text-[11px]" style={{ color: "var(--text-dim)" }}>Formats supportés : CSV, XLSX, XLS, PDF, DOCX</div>
        </div>
      </Modal>
    </div>
  );
}
