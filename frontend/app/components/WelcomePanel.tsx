"use client";

import { ArrowUpRight, FileText, Sparkles, Table2, Upload } from "lucide-react";

interface Props {
  onUpload: () => void;
}

const capabilities = [
  { icon: Table2, title: "Explorer vos données", text: "Tableaux CSV et Excel" },
  { icon: FileText, title: "Interroger vos documents", text: "PDF et documents Word" },
  { icon: Sparkles, title: "Obtenir des insights", text: "Analyses en langage naturel" },
];

export default function WelcomePanel({ onUpload }: Props) {
  return (
    <div className="welcome-panel">
      <div className="welcome-panel__halo" aria-hidden="true" />
      <div className="welcome-panel__content">
        <div className="welcome-panel__eyebrow"><Sparkles size={14} /> Intelligence de données</div>
        <h1>Vos données ont<br />quelque chose à dire.</h1>
        <p className="welcome-panel__description">
          Importez une source, posez vos questions et obtenez des réponses claires, sans écrire une ligne de code.
        </p>

        <button className="welcome-panel__upload" onClick={onUpload}>
          <span className="welcome-panel__upload-icon"><Upload size={20} /></span>
          <span>
            <strong>Importer un fichier</strong>
            <small>CSV, Excel, PDF ou Word</small>
          </span>
          <ArrowUpRight className="welcome-panel__arrow" size={19} />
        </button>

        <p className="welcome-panel__hint">Glissez-déposez aussi votre fichier dans l’espace Sources.</p>

        <div className="welcome-panel__capabilities">
          {capabilities.map(({ icon: Icon, title, text }) => (
            <div className="welcome-panel__capability" key={title}>
              <Icon size={18} strokeWidth={1.7} />
              <div><strong>{title}</strong><span>{text}</span></div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
