"use client";

import { ArrowUpRight, FileText, Sparkles, Table2, Upload } from "lucide-react";

const capabilities = [
  { icon: Table2, title: "Explorer vos données", text: "Tableaux CSV et Excel" },
  { icon: FileText, title: "Interroger vos documents", text: "PDF et documents Word" },
  { icon: Sparkles, title: "Obtenir des insights", text: "Analyses en langage naturel" },
];

export default function WelcomeScreen({ onUpload }: { onUpload: () => void }) {
  return (
    <div className="flex h-full min-h-0 flex-1 overflow-y-auto px-4 py-8">
      <div className="m-auto w-full max-w-[520px] text-center">
        <span className="text-[11px] uppercase tracking-[0.16em]" style={{ color: "var(--text-dim)" }}>
          Intelligence de données
        </span>

        <h1 className="mt-4 mb-3 font-serif text-[clamp(28px,4vw,40px)] font-medium leading-[1.15] tracking-tight" style={{ color: "var(--text-main)" }}>
          Vos données ont quelque chose à dire.
        </h1>

        <p className="mx-auto mb-8 max-w-[420px] text-[15px] leading-relaxed" style={{ color: "var(--text-muted)" }}>
          Importez une source, posez vos questions et obtenez des réponses claires, sans écrire une ligne de code.
        </p>

        <button
          onClick={onUpload}
          className="flex w-full items-center gap-3.5 rounded-md border px-4 py-3.5 text-left transition-colors hover:bg-[var(--bubble-ai)]"
          style={{ borderColor: "var(--border-color)" }}
        >
          <span className="grid size-9 shrink-0 place-items-center rounded-md border" style={{ borderColor: "var(--border-color)", color: "var(--accent)" }}>
            <Upload size={17} strokeWidth={1.6} />
          </span>
          <span className="flex-1">
            <strong className="block text-[14px] font-medium" style={{ color: "var(--text-main)" }}>Importer un fichier</strong>
            <small className="mt-0.5 block text-[12px]" style={{ color: "var(--text-muted)" }}>CSV, Excel, PDF ou Word</small>
          </span>
          <ArrowUpRight size={17} style={{ color: "var(--text-muted)" }} />
        </button>

        <p className="my-7 text-[11px]" style={{ color: "var(--text-dim)" }}>
          Glissez-déposez aussi votre fichier dans l&rsquo;espace Sources.
        </p>

        <div className="divide-y border-y text-left" style={{ borderColor: "var(--border-muted)" }}>
          {capabilities.map(({ icon: Icon, title, text }) => (
            <div key={title} className="flex items-center gap-3.5 py-3.5" style={{ borderColor: "var(--border-muted)" }}>
              <Icon size={16} strokeWidth={1.6} style={{ color: "var(--accent)" }} className="shrink-0" />
              <div>
                <strong className="block text-[13px] font-medium" style={{ color: "var(--text-main)" }}>{title}</strong>
                <span className="mt-0.5 block text-[11.5px]" style={{ color: "var(--text-muted)" }}>{text}</span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
