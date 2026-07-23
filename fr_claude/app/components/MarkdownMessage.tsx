"use client";

import type { JSX, ReactNode } from "react";

export type SourceRef = { page: number; text: string };

// Rend une citation inline "[n]" (insérée par le LLM) en badge cliquable qui
// ouvre l'extrait source correspondant (sources[n-1]). Sans sources
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
      className="mx-0.5 inline-flex h-[15px] min-w-[15px] items-center justify-center rounded-full border px-1 align-super text-[10px] font-bold leading-none"
      style={{ borderColor: "var(--accent)", background: "var(--accent-soft)", color: "var(--accent)" }}
    >
      {index}
    </button>
  );
}

function renderInline(text: string, sources?: SourceRef[], onSourceClick?: (src: SourceRef) => void): ReactNode[] {
  const parts = text.split(/(\*\*.*?\*\*|`.*?`|\[\d+\])/g);
  return parts.map((part, j) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={j} style={{ fontWeight: 600, color: "var(--text-main)" }}>
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code
          key={j}
          className="rounded px-1.5 py-0.5 text-[12px]"
          style={{ background: "var(--border-color)", fontFamily: "var(--font-mono, monospace)" }}
        >
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

const PROPOSITION_KEYWORDS = ["PROPOSITION", "SUGGESTION", "QUESTION", "IDÉE", "IDEE"];

interface MarkdownMessageProps {
  text: string;
  onPropositionClick?: (text: string) => void;
  // Permet de scinder le texte en deux blocs : le contenu principal
  // ("content") et les suggestions/propositions détectées en fin de réponse
  // ("suggestions"), pour pouvoir intercaler les graphiques entre les deux.
  section?: "all" | "content" | "suggestions";
  sources?: SourceRef[];
  onSourceClick?: (src: SourceRef) => void;
}

export default function MarkdownMessage({ text, onPropositionClick, section = "all", sources, onSourceClick }: MarkdownMessageProps) {
  const lines = text.split("\n");
  let inPropositions = false;
  const shouldInclude = () =>
    section === "all" || (section === "content" ? !inPropositions : inPropositions);

  return (
    <div>
      {lines.map((line, i) => {
        const clean = line.trim();

        const headerMatch = clean.match(/^(#{1,6})\s+(.*)$/);
        const boldHeaderMatch = clean.match(/^\*\*([^*]+)\*\*\s*:?$/);
        let isHeader = false;
        let level = 3;
        let content = "";

        if (headerMatch) {
          isHeader = true;
          level = headerMatch[1].length;
          content = headerMatch[2];
        } else if (boldHeaderMatch) {
          isHeader = true;
          level = 3;
          content = boldHeaderMatch[1];
        }

        if (isHeader) {
          const upper = content.toUpperCase();
          if (PROPOSITION_KEYWORDS.some((k) => upper.includes(k))) {
            inPropositions = true;
          } else if (level <= 3) {
            inPropositions = false;
          }
          if (!shouldInclude()) return null;
          const Tag = `h${level}` as keyof JSX.IntrinsicElements;
          return (
            <Tag
              key={i}
              style={{
                margin: level === 1 ? "18px 0 10px" : level === 2 ? "16px 0 8px" : "12px 0 6px",
                fontWeight: 600,
                fontSize: level === 1 ? "18px" : level === 2 ? "16px" : level === 3 ? "14px" : "13px",
                color: "var(--text-main)",
                lineHeight: 1.4,
              }}
            >
              {renderInline(content, sources, onSourceClick)}
            </Tag>
          );
        }

        const isBullet = clean.startsWith("- ") || clean.startsWith("* ") || clean.startsWith("• ");
        const numMatch = clean.match(/^(\d+)\.\s+(.*)$/);

        if (isBullet || numMatch) {
          const listContent = isBullet ? clean.substring(2) : numMatch![2];
          const prefix = isBullet ? "•" : `${numMatch![1]}.`;

          if (inPropositions && onPropositionClick) {
            if (!shouldInclude()) return null;
            return (
              <button
                key={i}
                onClick={() => onPropositionClick(listContent.replace(/\*\*/g, ""))}
                className="my-1.5 block w-fit max-w-[95%] border-l-2 py-1.5 pl-3 pr-1 text-left text-[13px] font-medium transition-colors hover:bg-[var(--bubble-ai)]"
                style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
              >
                {renderInline(listContent, sources, onSourceClick)}
              </button>
            );
          }

          if (!shouldInclude()) return null;
          return (
            <div key={i} className="my-1.5 ml-2 flex items-start gap-2">
              <span
                style={{ color: "var(--accent)", fontWeight: numMatch ? 700 : 400, fontSize: numMatch ? "13px" : "inherit" }}
              >
                {prefix}
              </span>
              <span className="flex-1" style={{ textAlign: "justify" }}>{renderInline(listContent, sources, onSourceClick)}</span>
            </div>
          );
        }

        if (clean === "") {
          return shouldInclude() ? <div key={i} className="h-2" /> : null;
        }

        const upperLine = clean.toUpperCase();
        if (PROPOSITION_KEYWORDS.some((k) => upperLine.includes(k))) {
          inPropositions = true;
        }

        if (!shouldInclude()) return null;
        return (
          <p key={i} className="my-1" style={{ textAlign: "justify" }}>
            {renderInline(line, sources, onSourceClick)}
          </p>
        );
      })}
    </div>
  );
}
