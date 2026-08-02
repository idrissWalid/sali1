"use client";

import React, { useState } from "react";
import { toggleTheme, useTheme } from "@/hooks/use-theme";
import { API_URL } from "@/lib/api";
import {
  ArrowLeft, CheckCircle2, XCircle, AlertTriangle, MinusCircle, Sun, Moon,
  Target, Gauge, Trophy, Timer, FlaskConical, BarChart3, Loader2,
} from "lucide-react";
import { Download } from "@/components/animate-ui/icons/download";
import {
  Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
} from "recharts";

interface Candidat {
  modele: string;
  libelle: string;
  conforme?: boolean;
  qualite?: string;
  metrique_qualite?: string;
  remediation?: string;
  erreur?: string;
  violations?: string[];
  avertissements?: string[];
  performances?: Record<string, number | null>;
  hypotheses?: Record<string, unknown>;
  coefficients?: Record<string, number | null>;
  odds_ratios?: Record<string, number | null>;
  p_values?: Record<string, number | null>;
  importances?: Record<string, number | null>;
  confusion_matrix?: number[][];
  seuil_decision?: number | null;
  variables_non_significatives?: string[];
  roc_curve?: { fpr: number | null; tpr: number | null; threshold: number | null }[];
  pr_curve?: { recall: number | null; precision: number | null }[];
}

/** Ce que le pipeline sérialisé attend en entrée — sert à construire le
 *  formulaire de simulation sans que l'utilisateur ait à deviner les colonnes. */
interface Artefact {
  disponible?: boolean;
  raison?: string;
  colonnes_attendues?: string[];
  colonnes_numeriques?: string[];
  colonnes_categorielles?: string[];
  modalites?: Record<string, string[]>;
  bornes_numeriques?: Record<string, { min: number | null; max: number | null; median: number | null }>;
  classes?: string[] | null;
  seuil_decision?: number | null;
}

export interface SupervisedReport {
  interpretation?: string;
  famille?: string;
  cible?: string;
  variables?: string[];
  n_observations?: number;
  n_train?: number;
  n_test?: number;
  classes?: string[] | null;
  ratio_minoritaire?: number | null;
  metrique_selection?: string;
  modele_retenu?: Candidat;
  candidats?: Candidat[];
  statut_final?: string;
  qualite?: string;
  metrique_qualite?: string;
  artefact?: Artefact;
  budget_secondes?: number;
  duree_secondes?: number;
  sortie_anticipee?: boolean;
  avertissements?: string[];
  violations?: string[];
  _engine?: string;
}

interface ModelInfo {
  id: string;
  name: string;
  type: string;
  created_at: string;
  metrics: SupervisedReport;
}

const fr = (v?: number | null, d = 3) =>
  typeof v === "number" && isFinite(v) ? v.toLocaleString("fr-FR", { maximumFractionDigits: d }) : "—";

const FAMILLES: Record<string, string> = {
  regression: "Régression",
  classification: "Classification",
  classification_desequilibree: "Classification déséquilibrée",
};

/** Le statut dit si le modèle est utilisable ; la qualité dit à quel point il
 *  est bon. Les deux sont distincts : franchir le plancher de bruit ne vaut pas
 *  quitus sur la qualité prédictive. */
const STATUTS: Record<string, { label: string; cls: string; Icon: typeof CheckCircle2 }> = {
  MODELE_VALIDE: {
    label: "Modèle validé",
    cls: "bg-green-50 text-green-700 border-green-200 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800",
    Icon: CheckCircle2,
  },
  HYPOTHESES_VIOLEES: {
    label: "À améliorer",
    cls: "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800",
    Icon: AlertTriangle,
  },
  AUCUN_MODELE_UTILE: {
    label: "Aucun modèle utile",
    cls: "bg-red-50 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-400 dark:border-red-800",
    Icon: XCircle,
  },
};

const QUALITES: Record<string, string> = {
  excellente: "text-green-600 dark:text-green-400",
  bonne: "text-green-600 dark:text-green-400",
  moderee: "text-amber-600 dark:text-amber-400",
  faible: "text-orange-600 dark:text-orange-400",
  insuffisante: "text-red-600 dark:text-red-400",
};

function Card({ title, extra, children, delay }: { title: React.ReactNode; extra?: React.ReactNode; children: React.ReactNode; delay: number }) {
  return (
    <div className="dashboard-panel bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm sv-card" style={{ animationDelay: `${delay}ms` }}>
      <div className="mb-4 flex items-center justify-between gap-2 border-b border-gray-100 dark:border-gray-800 pb-3">
        <h3 className="text-sm font-bold uppercase tracking-wide text-gray-600 dark:text-gray-300">{title}</h3>
        {extra}
      </div>
      {children}
    </div>
  );
}

function InlineMarkdown({ texte }: { texte: string }) {
  const morceaux = texte.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g);
  return morceaux.map((morceau, i) => {
    if (morceau.startsWith("**") && morceau.endsWith("**")) return <strong key={i}>{morceau.slice(2, -2)}</strong>;
    if (morceau.startsWith("`") && morceau.endsWith("`")) return <code key={i}>{morceau.slice(1, -1)}</code>;
    if (morceau.startsWith("*") && morceau.endsWith("*")) return <em key={i}>{morceau.slice(1, -1)}</em>;
    return morceau;
  });
}

function Prose({ texte }: { texte: string }) {
  const lignes = texte.replace(/\r/g, "").split("\n");
  const elements: React.ReactNode[] = [];
  let liste: string[] = [];
  const viderListe = () => {
    if (liste.length === 0) return;
    elements.push(<ul key={`list-${elements.length}`}>{liste.map((item, i) => <li key={i}><InlineMarkdown texte={item} /></li>)}</ul>);
    liste = [];
  };

  lignes.forEach((ligne) => {
    const contenu = ligne.trim();
    const item = contenu.match(/^[-*]\s+(.+)/);
    if (item) { liste.push(item[1]); return; }
    viderListe();
    if (!contenu) return;
    const titre = contenu.match(/^(#{1,3})\s+(.+)/);
    if (titre) {
      const Tag = titre[1].length === 1 ? "h2" : "h3";
      elements.push(<Tag key={elements.length}><InlineMarkdown texte={titre[2]} /></Tag>);
    } else {
      elements.push(<p key={elements.length}><InlineMarkdown texte={contenu} /></p>);
    }
  });
  viderListe();
  return <div className="sv-markdown">{elements}</div>;
}

function Row({ k, v, accent }: { k: string; v: React.ReactNode; accent?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5 text-sm border-b border-gray-50 dark:border-gray-800/50 last:border-0">
      <span className="text-gray-500 dark:text-gray-400">{k}</span>
      <span className={`font-mono ${accent ?? "text-gray-900 dark:text-gray-100"}`}>{v}</span>
    </div>
  );
}

function StatTile({ icon: Icon, label, value, accent, delay }: { icon: React.ComponentType<{ className?: string }>; label: string; value: React.ReactNode; accent?: string; delay: number }) {
  return (
    <div className="dashboard-stat bg-white dark:bg-[#1a1a1a] border border-gray-200 dark:border-gray-800 rounded-2xl shadow-sm flex items-start gap-4 sv-card" style={{ animationDelay: `${delay}ms` }}>
      <div className={`p-3 rounded-xl ${accent ?? "bg-gray-50 dark:bg-[#222] text-blue-500"}`}>
        <Icon className="w-6 h-6" />
      </div>
      <div className="min-w-0">
        <p className="text-sm text-gray-500 dark:text-gray-400 font-medium">{label}</p>
        <p className="mt-1 text-2xl font-bold truncate">{value}</p>
      </div>
    </div>
  );
}

/** Barre horizontale : le poids relatif se lit d'un coup d'œil, là où une
 *  colonne de nombres oblige à comparer mentalement. */
function Barres({ valeurs, signe }: { valeurs: Record<string, number | null>; signe?: boolean }) {
  const entrees = Object.entries(valeurs)
    .filter(([, v]) => typeof v === "number" && isFinite(v))
    .sort((a, b) => Math.abs(b[1] as number) - Math.abs(a[1] as number))
    .slice(0, 12);
  if (entrees.length === 0) return <p className="text-sm text-gray-400">Non disponible.</p>;
  const max = Math.max(...entrees.map(([, v]) => Math.abs(v as number))) || 1;

  return (
    <div className="flex flex-col gap-2">
      {entrees.map(([nom, v]) => {
        const val = v as number;
        const negatif = signe && val < 0;
        return (
          <div key={nom} className="flex items-center gap-3 text-sm">
            <span className="w-40 shrink-0 truncate text-gray-600 dark:text-gray-300" title={nom}>{nom}</span>
            <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
              <div
                className={`h-full rounded-full ${negatif ? "bg-rose-400" : "bg-blue-500"}`}
                style={{ width: `${(Math.abs(val) / max) * 100}%` }}
              />
            </div>
            <span className="w-20 shrink-0 text-right font-mono text-xs text-gray-500 dark:text-gray-400">{fr(val, 4)}</span>
          </div>
        );
      })}
    </div>
  );
}

function MatriceConfusion({ matrice, classes, delay }: { matrice: number[][]; classes?: string[] | null; delay: number }) {
  const valeurs = matrice.flat();
  const maximum = Math.max(...valeurs, 1);
  const total = valeurs.reduce((somme, valeur) => somme + valeur, 0);
  const correctes = matrice.reduce((somme, ligne, i) => somme + (ligne[i] ?? 0), 0);
  const erreurs = total - correctes;
  const taux = total > 0 ? (correctes / total) * 100 : 0;
  const labels = Array.from(
    { length: Math.max(matrice.length, ...matrice.map((ligne) => ligne.length)) },
    (_, i) => classes?.[i] ?? String(i),
  );

  return (
    <Card
      title="Matrice de confusion"
      delay={delay}
      extra={<span className="text-xs text-gray-400">Lignes : réel · Colonnes : prédit</span>}
    >
      <div className="confusion-layout">
        <div className="confusion-summary">
          <div className="confusion-kpi">
            <span>Bonnes prédictions</span>
            <strong className="text-emerald-600 dark:text-emerald-400">{correctes.toLocaleString("fr-FR")}</strong>
          </div>
          <div className="confusion-kpi">
            <span>Erreurs</span>
            <strong className="text-rose-600 dark:text-rose-400">{erreurs.toLocaleString("fr-FR")}</strong>
          </div>
          <div className="confusion-kpi">
            <span>Taux correct</span>
            <strong>{taux.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %</strong>
          </div>
        </div>

        <div className="sv-scroll overflow-x-auto pb-2">
          <div className="confusion-matrix" style={{ minWidth: `${Math.max(420, labels.length * 88 + 150)}px` }}>
            <div className="confusion-axis-title" style={{ gridColumn: `2 / span ${labels.length}` }}>Classe prédite</div>
            <div />
            {labels.map((label, j) => (
              <div key={`prediction-${j}`} className="confusion-column-label" title={label}>{label}</div>
            ))}
            {matrice.map((ligne, i) => (
              <React.Fragment key={`actual-${i}`}>
                <div className="confusion-row-label" title={labels[i]}>
                  <span>Réel</span>{labels[i]}
                </div>
                {labels.map((_, j) => {
                  const valeur = ligne[j] ?? 0;
                  const intensite = valeur / maximum;
                  const correcte = i === j;
                  return (
                    <div
                      key={`${i}-${j}`}
                      className={`confusion-cell ${correcte ? "confusion-cell--correct" : "confusion-cell--error"}`}
                      style={{ "--cell-intensity": Math.max(0.08, intensite) } as React.CSSProperties}
                      title={`${labels[i]} réel, ${labels[j]} prédit : ${valeur}`}
                    >
                      <strong>{valeur.toLocaleString("fr-FR")}</strong>
                      <span>{total > 0 ? `${((valeur / total) * 100).toFixed(1)} %` : "0 %"}</span>
                    </div>
                  );
                })}
              </React.Fragment>
            ))}
          </div>
        </div>

        <div className="confusion-legend">
          <span><i className="bg-emerald-500" /> Bonne classification</span>
          <span><i className="bg-rose-500" /> Confusion entre classes</span>
          <span className="text-gray-400">Une couleur plus intense représente plus d’observations.</span>
        </div>
      </div>
    </Card>
  );
}

/** Courbe ROC ou précision-rappel, avec sa ligne de référence.
 *
 *  La diagonale (ROC) et la prévalence (PR) ne sont pas décoratives : sans elles
 *  une AUC de 0,7 ou une PR-AUC de 0,4 sont ininterprétables — on ne sait pas ce
 *  que « le hasard » aurait donné.
 */
function Courbe({
  titre, points, cleX, cleY, labelX, labelY, aire, labelAire, reference, labelRef, couleur, sombre, delay,
}: {
  titre: string;
  points: Record<string, number | null>[];
  cleX: string; cleY: string; labelX: string; labelY: string;
  aire?: number | null; labelAire: string;
  reference: "diagonale" | number | null; labelRef: string;
  couleur: string; sombre: boolean; delay: number;
}) {
  const data = points
    .filter((p) => typeof p[cleX] === "number" && typeof p[cleY] === "number")
    .map((p) => ({ x: p[cleX] as number, y: p[cleY] as number }));
  if (data.length === 0) return null;

  const infobulle = sombre
    ? { borderRadius: 12, border: "1px solid #333", background: "rgba(20,20,20,0.95)", color: "#fff" }
    : { borderRadius: 12, border: "1px solid #e5e7eb", background: "#fff", color: "#111" };

  return (
    <Card
      title={titre}
      delay={delay}
      extra={
        <span className="font-mono text-xs text-gray-500 dark:text-gray-400">
          {labelAire} {fr(aire)}
        </span>
      }
    >
      <div style={{ width: "100%", height: 260 }}>
        <ResponsiveContainer>
          <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 18 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
            <XAxis
              dataKey="x" type="number" domain={[0, 1]}
              tick={{ fill: "#888", fontSize: 11 }}
              label={{ value: labelX, position: "insideBottom", offset: -10, fill: "#888", fontSize: 11 }}
            />
            <YAxis
              type="number" domain={[0, 1]}
              tick={{ fill: "#888", fontSize: 11 }} width={44}
              label={{ value: labelY, angle: -90, position: "insideLeft", fill: "#888", fontSize: 11 }}
            />
            <Tooltip
              contentStyle={infobulle}
              formatter={(v: unknown) => fr(v as number)}
              labelFormatter={(v) => `${labelX} : ${fr(v as number)}`}
            />
            {reference === "diagonale" ? (
              <Line
                type="linear" dataKey="x" stroke="#9ca3af" strokeDasharray="4 4"
                strokeWidth={1} dot={false} name="Hasard" isAnimationActive={false}
              />
            ) : typeof reference === "number" ? (
              <ReferenceLine
                y={reference} stroke="#9ca3af" strokeDasharray="4 4"
                label={{ value: labelRef, fill: "#9ca3af", fontSize: 10, position: "insideBottomRight" }}
              />
            ) : null}
            <Line
              type="monotone" dataKey="y" stroke={couleur} strokeWidth={2.5}
              dot={false} name={labelY} isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {reference === "diagonale" && (
        <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
          La diagonale représente un classement au hasard : plus la courbe s&apos;en éloigne vers le
          haut-gauche, meilleur est le modèle.
        </p>
      )}
    </Card>
  );
}

/** Onglet simulation : on saisit un profil, le modèle prédit.
 *
 *  Le formulaire est construit à partir des colonnes BRUTES attendues par le
 *  pipeline sérialisé — pas des colonnes encodées, que l'utilisateur n'a aucune
 *  raison de connaître.
 */
function Simulation({ modelId, artefact, estRegression, cible, delay }: {
  modelId: string; artefact: Artefact; estRegression: boolean; cible?: string; delay: number;
}) {
  const numeriques = artefact.colonnes_numeriques ?? [];
  const categorielles = artefact.colonnes_categorielles ?? [];
  const bornes = artefact.bornes_numeriques ?? {};
  const modalites = artefact.modalites ?? {};

  const [valeurs, setValeurs] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    numeriques.forEach((c) => { initial[c] = String(bornes[c]?.median ?? ""); });
    categorielles.forEach((c) => { initial[c] = modalites[c]?.[0] ?? ""; });
    return initial;
  });
  const [resultat, setResultat] = useState<{ classe?: string; valeur?: number; probas?: Record<string, number> } | null>(null);
  const [enCours, setEnCours] = useState(false);
  const [erreur, setErreur] = useState("");

  if (!artefact.disponible) {
    return (
      <Card title={<span className="flex items-center gap-2"><FlaskConical size={14} /> Simulation</span>} delay={delay}>
        <p className="text-sm text-gray-500 dark:text-gray-400">
          Aucun modèle exportable n&apos;a pu être produit pour ce tournoi
          {artefact.raison ? ` (${artefact.raison})` : ""}. La simulation n&apos;est pas disponible.
        </p>
      </Card>
    );
  }

  const predire = async () => {
    setEnCours(true);
    setErreur("");
    setResultat(null);
    try {
      const apiUrl = API_URL;
      // Les numériques doivent partir en nombre : une chaîne ferait échouer le
      // StandardScaler du pipeline.
      const features: Record<string, string | number> = {};
      numeriques.forEach((c) => { features[c] = Number(valeurs[c]); });
      categorielles.forEach((c) => { features[c] = valeurs[c]; });

      const res = await fetch(`${apiUrl}/api/models/${modelId}/predict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ features }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || "Échec de la prédiction.");
      setResultat({
        classe: data.classe_predite ?? (estRegression ? undefined : String(data.prediction?.[0])),
        valeur: estRegression ? Number(data.prediction?.[0]) : undefined,
        probas: data.probabilites,
      });
    } catch (e) {
      setErreur(e instanceof Error ? e.message : "Erreur inattendue.");
    } finally {
      setEnCours(false);
    }
  };

  const champ = "w-full min-h-12 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-[#181818] px-4 py-3 text-sm leading-6 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/15";

  return (
    <Card title={<span className="flex items-center gap-2"><FlaskConical size={14} /> Simulation</span>} delay={delay}>
      <p className="mb-4 text-sm text-gray-500 dark:text-gray-400">
        Renseignez un profil : le modèle prédit {estRegression ? <>la valeur de <strong>{cible}</strong></> : <>la classe de <strong>{cible}</strong></>}.
      </p>

      <div className="simulation-fields">
        {numeriques.map((c) => (
          <label key={c} className="simulation-field">
            <span>{c}</span>
            <input
              type="number" className={champ} value={valeurs[c] ?? ""}
              onChange={(e) => setValeurs((v) => ({ ...v, [c]: e.target.value }))}
            />
            {bornes[c] && (
              <span className="text-xs text-gray-400">
                observé entre {fr(bornes[c].min, 2)} et {fr(bornes[c].max, 2)}
              </span>
            )}
          </label>
        ))}
        {categorielles.map((c) => (
          <label key={c} className="simulation-field">
            <span>{c}</span>
            <select
              className={champ} value={valeurs[c] ?? ""}
              onChange={(e) => setValeurs((v) => ({ ...v, [c]: e.target.value }))}
            >
              {(modalites[c] ?? []).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>
        ))}
      </div>

      <button
        onClick={predire} disabled={enCours}
        className="mt-5 inline-flex items-center gap-2 rounded-xl bg-blue-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-blue-700 disabled:opacity-60"
      >
        {enCours ? <><Loader2 size={15} className="animate-spin" /> Prédiction…</> : <>Prédire</>}
      </button>

      {erreur && <p className="mt-4 text-sm text-red-500">{erreur}</p>}

      {resultat && (
        <div className="mt-5 rounded-xl border border-gray-100 dark:border-gray-800 bg-gray-50 dark:bg-[#202020] p-5">
          <div className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
            Prédiction
          </div>
          <div className="mt-1 text-2xl font-bold">
            {estRegression ? fr(resultat.valeur, 2) : resultat.classe}
          </div>
          {resultat.probas && (
            <div className="mt-4 flex flex-col gap-2">
              {Object.entries(resultat.probas).map(([cl, p]) => (
                <div key={cl} className="flex items-center gap-3 text-sm">
                  <span className="w-28 shrink-0 truncate text-gray-600 dark:text-gray-300">{cl}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                    <div className="h-full rounded-full bg-blue-500" style={{ width: `${p * 100}%` }} />
                  </div>
                  <span className="w-14 shrink-0 text-right font-mono text-xs text-gray-500 dark:text-gray-400">
                    {(p * 100).toFixed(1)} %
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export default function SupervisedModelView({ model, onBack }: { model: ModelInfo; onBack: () => void }) {
  const theme = useTheme();
  const r = model.metrics || {};
  const retenu: Candidat = r.modele_retenu ?? { modele: "", libelle: "—" };
  const perf = retenu.performances || {};
  const estRegression = r.famille === "regression";
  const performancePrincipale = estRegression ? perf.r2_test : perf.accuracy_test;
  const performanceAffichee = typeof performancePrincipale === "number"
    ? `${(performancePrincipale * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`
    : "—";

  const statut = STATUTS[r.statut_final ?? ""] ?? {
    label: r.statut_final ?? "Inconnu",
    cls: "bg-gray-100 text-gray-600 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-700",
    Icon: MinusCircle,
  };
  const StatutIcon = statut.Icon;
  const artefact = r.artefact ?? {};
  const [onglet, setOnglet] = useState<"rapport" | "simulation">("rapport");

  const apiUrl = API_URL;

  return (
    <div className="dashboard-shell min-h-screen w-full bg-gray-50 dark:bg-[#111] text-gray-900 dark:text-gray-100 font-sans">
      <style>{`
        @keyframes sv-fade-up { from { opacity: 0; transform: translateY(10px) } to { opacity: 1; transform: translateY(0) } }
        .sv-card { animation: sv-fade-up .45s ease-out both; }
        .sv-scroll::-webkit-scrollbar { height: 6px; width: 6px; }
        .sv-scroll::-webkit-scrollbar-thumb { background-color: rgba(150,150,150,.3); border-radius: 10px; }
        .dashboard-shell { padding: 32px clamp(20px, 4vw, 72px) 48px; }
        .dashboard-container { width: min(100%, 1680px); margin: 0 auto; display: grid; gap: 24px; }
        .dashboard-header { gap: 24px; }
        .dashboard-stats { gap: 16px; }
        .dashboard-panel { padding: 24px; }
        .dashboard-stat { min-height: 104px; padding: 20px; }
        .performance-hero { min-height: 190px; display: flex; align-items: center; justify-content: space-between; overflow: hidden; padding: clamp(28px, 4vw, 52px); border: 1px solid rgba(59,130,246,.22); border-radius: 24px; color: white; background: linear-gradient(125deg,#0f55d8 0%,#2563eb 52%,#7c3aed 120%); box-shadow: 0 18px 48px rgba(37,99,235,.18); }
        .performance-hero__eyebrow { display: block; margin-bottom: 8px; font-size: 12px; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; opacity: .78; }
        .performance-hero strong { display: block; font-size: clamp(54px,8vw,92px); line-height: .95; letter-spacing: -.06em; }
        .performance-hero p { margin-top: 14px; font-size: 14px; opacity: .82; }
        .performance-hero > svg { width: clamp(80px,12vw,150px); height: auto; opacity: .18; stroke-width: 1.2; }
        .sv-markdown { display: grid; gap: 12px; color: #4b5563; font-size: 14px; line-height: 1.75; }
        [data-theme="dark"] .sv-markdown { color: #d1d5db; }
        .sv-markdown h2 { margin-top: 8px; color: inherit; font-size: 19px; font-weight: 750; }
        .sv-markdown h3 { margin-top: 6px; color: inherit; font-size: 16px; font-weight: 700; }
        .sv-markdown ul { display: grid; gap: 7px; padding-left: 20px; list-style: disc; }
        .sv-markdown code { padding: 2px 6px; border-radius: 5px; background: rgba(127,127,127,.12); font-family: monospace; font-size: .9em; }
        .simulation-fields { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(100%,280px),1fr)); gap: 20px; }
        .simulation-field { min-width: 0; display: flex; flex-direction: column; gap: 8px; }
        .simulation-field > span:first-child { overflow-wrap: anywhere; color: #4b5563; font-size: 13px; font-weight: 650; line-height: 1.45; }
        [data-theme="dark"] .simulation-field > span:first-child { color: #d1d5db; }
        .confusion-layout { display: grid; gap: 20px; }
        .confusion-summary { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
        .confusion-kpi { display: flex; flex-direction: column; gap: 4px; padding: 14px 16px; border-radius: 12px; background: color-mix(in srgb,currentColor 4%,transparent); border: 1px solid color-mix(in srgb,currentColor 9%,transparent); }
        .confusion-kpi span { color: #6b7280; font-size: 12px; font-weight: 600; }
        .confusion-kpi strong { font-size: 22px; line-height: 1.2; }
        .confusion-matrix { display: grid; grid-template-columns: minmax(110px, 1.35fr) repeat(${Math.max(retenu.confusion_matrix?.[0]?.length ?? 0, 1)}, minmax(72px, 1fr)); gap: 6px; align-items: stretch; }
        .confusion-axis-title { padding: 2px 8px 6px; text-align: center; color: #6b7280; font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
        .confusion-column-label, .confusion-row-label { min-width: 0; color: #4b5563; font-size: 12px; font-weight: 650; }
        [data-theme="dark"] .confusion-column-label, [data-theme="dark"] .confusion-row-label { color: #d1d5db; }
        .confusion-column-label { padding: 6px; text-align: center; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .confusion-row-label { display: flex; flex-direction: column; justify-content: center; padding: 8px 12px; overflow: hidden; text-overflow: ellipsis; }
        .confusion-row-label span { color: #9ca3af; font-size: 9px; letter-spacing: .08em; text-transform: uppercase; }
        .confusion-cell { min-height: 76px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; border-radius: 12px; border: 1px solid transparent; }
        .confusion-cell strong { font-size: 18px; line-height: 1.2; }
        .confusion-cell span { font-size: 10px; opacity: .7; }
        .confusion-cell--correct { color: rgb(4 120 87); background: rgba(16,185,129,var(--cell-intensity)); border-color: rgba(16,185,129,.2); }
        .confusion-cell--error { color: rgb(190 24 93); background: rgba(244,63,94,var(--cell-intensity)); border-color: rgba(244,63,94,.16); }
        [data-theme="dark"] .confusion-cell--correct { color: rgb(167 243 208); }
        [data-theme="dark"] .confusion-cell--error { color: rgb(254 205 211); }
        .confusion-legend { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 20px; font-size: 11px; color: #6b7280; }
        .confusion-legend span { display: inline-flex; align-items: center; gap: 7px; }
        .confusion-legend i { width: 9px; height: 9px; border-radius: 3px; }
        @media (max-width: 640px) {
          .dashboard-shell { padding: 20px 14px 32px; }
          .dashboard-container { gap: 16px; }
          .dashboard-header { align-items: flex-start; flex-direction: column; gap: 16px; }
          .dashboard-header > div:last-child { width: 100%; flex-wrap: wrap; }
          .dashboard-stats { gap: 10px; }
          .dashboard-panel { padding: 18px; }
          .dashboard-stat { padding: 16px; }
          .confusion-summary { grid-template-columns: 1fr; gap: 8px; }
          .confusion-kpi { flex-direction: row; align-items: center; justify-content: space-between; }
          .confusion-kpi strong { font-size: 18px; }
          .performance-hero { min-height: 160px; }
          .performance-hero > svg { display: none; }
        }
      `}</style>

      <div className="dashboard-container">
        {/* Header */}
        <div className="dashboard-header flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">{model.name}</h1>
            <p className="text-gray-500 dark:text-gray-400 mt-1 flex items-center gap-2">
              <Target className="w-4 h-4 text-blue-500" />
              {FAMILLES[r.famille ?? ""] ?? "Modèle supervisé"} — Cible : <span className="font-semibold text-gray-700 dark:text-gray-300">{r.cible}</span>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium ${statut.cls}`}>
              <StatutIcon size={15} /> {statut.label}
            </span>
            {artefact.disponible && (
              <a
                href={`${apiUrl}/api/models/${model.id}/download`}
                className="px-4 py-2 bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-[#333] transition flex items-center gap-2 text-sm font-medium"
                title="Pipeline scikit-learn sérialisé (encodage inclus) — s'utilise avec joblib.load()"
              >
                <Download animateOnHover size={15} /> Exporter (.pkl)
              </a>
            )}
            <button
              onClick={toggleTheme}
              aria-label={theme === "dark" ? "Activer le thème clair" : "Activer le thème sombre"}
              className="p-2 bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-[#333] transition flex items-center justify-center text-sm font-medium"
            >
              {theme === "dark" ? <Sun className="w-4 h-4 text-gray-400" /> : <Moon className="w-4 h-4 text-gray-500" />}
            </button>
            <button
              onClick={onBack}
              className="px-4 py-2 bg-white dark:bg-[#222] border border-gray-200 dark:border-gray-800 rounded-lg shadow-sm hover:bg-gray-50 dark:hover:bg-[#333] transition flex items-center gap-2 text-sm font-medium"
            >
              <ArrowLeft className="w-4 h-4" /> Retour
            </button>
          </div>
        </div>

        <div className="performance-hero sv-card">
          <div>
            <span className="performance-hero__eyebrow">Performance du modèle</span>
            <strong>{performanceAffichee}</strong>
            <p>{estRegression ? "Score R² sur les données de test" : "Prédictions correctes sur les données de test"}</p>
          </div>
          <Gauge aria-hidden="true" />
        </div>

        {/* Global Stats Overview */}
        <div className="dashboard-stats grid grid-cols-1 sm:grid-cols-3">
          <StatTile icon={Trophy} label="Modèle retenu" value={retenu.libelle ?? "—"} delay={0} />
          <StatTile
            icon={Gauge}
            label={`Qualité (${r.metrique_qualite ?? "—"})`}
            value={<span className={QUALITES[r.qualite ?? ""] ?? ""}>{r.qualite ?? "—"}</span>}
            accent="text-violet-500 bg-violet-50 dark:bg-violet-500/10"
            delay={60}
          />
          <StatTile
            icon={Timer}
            label="Durée d'exécution"
            value={`${fr(r.duree_secondes, 1)} s`}
            accent="text-amber-500 bg-amber-50 dark:bg-amber-500/10"
            delay={180}
          />
        </div>

        {/* Onglets : le rapport statistique et la mise en pratique du modèle
            répondent à deux questions distinctes — « puis-je y croire ? » et
            « que prédit-il pour ce cas ? ». */}
        <div className="flex gap-1 rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-[#1a1a1a] p-1 shadow-sm">
          {([
            { id: "rapport" as const, label: "Rapport", Icon: BarChart3 },
            { id: "simulation" as const, label: "Simulation", Icon: FlaskConical },
          ]).map(({ id, label, Icon }) => (
            <button
              key={id}
              onClick={() => setOnglet(id)}
              className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-colors ${
                onglet === id
                  ? "bg-blue-600 text-white shadow-sm"
                  : "text-gray-600 hover:bg-gray-50 dark:text-gray-300 dark:hover:bg-[#222]"
              }`}
            >
              <Icon size={15} /> {label}
            </button>
          ))}
        </div>

        {onglet === "rapport" ? (
          <>
        {/* Interprétation en langage naturel, générée par le LLM à partir du
            rapport — lue avant les détails statistiques. */}
        {r.interpretation && (
          <Card title="Interprétation" delay={200}>
            <Prose texte={r.interpretation} />
          </Card>
        )}

        {/* Le tournoi : tous les candidats, pas seulement le vainqueur */}
        <Card
          title="Modèles mis en concurrence"
          delay={250}
          extra={
            r.sortie_anticipee ? (
              <span className="inline-flex items-center gap-1 rounded-md border border-green-200 bg-green-50 px-2 py-0.5 text-xs font-semibold text-green-700 dark:border-green-800 dark:bg-green-900/30 dark:text-green-400">
                <CheckCircle2 size={12} /> arrêt anticipé
              </span>
            ) : null
          }
        >
          <div className="sv-scroll overflow-x-auto">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  <th className="px-3 py-2 font-semibold">Modèle</th>
                  <th className="px-3 py-2 text-right font-semibold">{estRegression ? "R² test" : "MCC"}</th>
                  <th className="px-3 py-2 text-right font-semibold">{estRegression ? "RMSE test" : "AUC"}</th>
                  <th className="px-3 py-2 font-semibold">Qualité</th>
                  <th className="px-3 py-2 font-semibold">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {(r.candidats ?? []).map((c) => {
                  const p = c.performances ?? {};
                  const gagnant = c.libelle === retenu.libelle;
                  return (
                    <tr key={c.modele} className={`border-t border-gray-100 dark:border-gray-800/70 ${gagnant ? "bg-blue-50/50 dark:bg-blue-500/5" : ""}`}>
                      <td className="px-3 py-2">
                        <span className={gagnant ? "font-semibold" : ""}>{c.libelle}</span>
                        {gagnant && <span className="ml-2 text-xs font-normal text-blue-500">retenu</span>}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">{fr(estRegression ? p.r2_test : p.mcc)}</td>
                      <td className="px-3 py-2 text-right font-mono">{fr(estRegression ? p.rmse_test : p.roc_auc, estRegression ? 0 : 3)}</td>
                      <td className={`px-3 py-2 ${QUALITES[c.qualite ?? ""] ?? ""}`}>{c.qualite ?? "—"}</td>
                      <td className="px-3 py-2">
                        {c.erreur ? (
                          <span className="text-red-500">échec</span>
                        ) : c.conforme ? (
                          <span className="inline-flex items-center gap-1 text-green-600 dark:text-green-400"><CheckCircle2 size={13} /> conforme</span>
                        ) : (
                          <span className="text-amber-600 dark:text-amber-400" title={(c.violations ?? []).join(" · ")}>
                            {(c.violations ?? []).length} écart(s)
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {retenu.remediation && (
            <p className="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700 dark:bg-blue-500/10 dark:text-blue-300">
              Remédiation appliquée : {retenu.remediation}
            </p>
          )}
        </Card>

        <div>
          <Card title="Performances (jeu de test)" delay={340}>
            {estRegression ? (
              <>
                <Row k="R² train" v={fr(perf.r2_train)} />
                <Row k="R² test" v={fr(perf.r2_test)} />
                <Row k="RMSE test" v={fr(perf.rmse_test, 1)} />
                <Row k="RMSE baseline (moyenne)" v={fr(perf.rmse_baseline, 1)} accent="text-gray-500 dark:text-gray-400" />
                <Row k="MAE test" v={fr(perf.mae_test, 1)} />
              </>
            ) : (
              <>
                <Row k="Accuracy test" v={fr(perf.accuracy_test)} />
                <Row k="Accuracy baseline (classe majoritaire)" v={fr(perf.accuracy_baseline)} accent="text-gray-500 dark:text-gray-400" />
                <Row k="Balanced accuracy" v={fr(perf.balanced_accuracy)} />
                <Row k="F1" v={fr(perf.f1)} />
                <Row k="MCC" v={fr(perf.mcc)} />
                <Row k="ROC-AUC" v={fr(perf.roc_auc)} />
                <Row k="PR-AUC" v={fr(perf.pr_auc)} />
              </>
            )}
            <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-400 dark:text-gray-500">
              {r.n_observations} observations — {r.n_train} en apprentissage, {r.n_test} en test.
            </div>
          </Card>
        </div>

        {/* Diagnostic principal d'une classification, placé immédiatement après les performances. */}
        {retenu.confusion_matrix && retenu.confusion_matrix.length > 0 && (
          <MatriceConfusion matrice={retenu.confusion_matrix} classes={r.classes} delay={370} />
        )}

        {/* Poids des variables */}
        {(retenu.coefficients || retenu.importances || retenu.odds_ratios) && (
          <Card
            title={retenu.odds_ratios ? "Odds ratios" : retenu.coefficients ? "Coefficients" : "Importance des variables"}
            delay={380}
          >
            <Barres
              valeurs={(retenu.odds_ratios || retenu.coefficients || retenu.importances) as Record<string, number | null>}
              signe={Boolean(retenu.coefficients && !retenu.odds_ratios)}
            />
            {(retenu.variables_non_significatives?.length ?? 0) > 0 && (
              <p className="mt-3 text-xs text-amber-600 dark:text-amber-400">
                Non significatives (p &gt; 0,05) : {retenu.variables_non_significatives!.join(", ")} — signalées, jamais retirées d&apos;office.
              </p>
            )}
          </Card>
        )}

        {/* Courbes ROC et précision-rappel */}
        {!estRegression && ((retenu.roc_curve?.length ?? 0) > 0 || (retenu.pr_curve?.length ?? 0) > 0) && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {(retenu.roc_curve?.length ?? 0) > 0 && (
              <Courbe
                titre="Courbe ROC"
                points={retenu.roc_curve as unknown as Record<string, number | null>[]}
                cleX="fpr" cleY="tpr"
                labelX="Taux de faux positifs" labelY="Taux de vrais positifs"
                aire={perf.roc_auc} labelAire="AUC"
                reference="diagonale" labelRef="hasard"
                couleur="#3b82f6" sombre={theme === "dark"} delay={400}
              />
            )}
            {(retenu.pr_curve?.length ?? 0) > 0 && (
              <Courbe
                titre="Courbe précision-rappel"
                points={retenu.pr_curve as unknown as Record<string, number | null>[]}
                cleX="recall" cleY="precision"
                labelX="Rappel" labelY="Précision"
                aire={perf.pr_auc} labelAire="PR-AUC"
                reference={perf.prevalence_positive ?? null} labelRef="prévalence"
                couleur="#8b5cf6" sombre={theme === "dark"} delay={430}
              />
            )}
          </div>
        )}

        {/* Avertissements informatifs */}
        {(r.avertissements?.length ?? 0) > 0 && (
          <div className="sv-card rounded-2xl border border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-900/10 p-6" style={{ animationDelay: "460ms" }}>
            <h3 className="mb-3 flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-amber-700 dark:text-amber-400">
              <AlertTriangle size={15} /> À signaler (n&apos;invalide pas le modèle)
            </h3>
            <ul className="list-disc list-inside space-y-1.5 text-sm text-amber-800 dark:text-amber-200/80">
              {r.avertissements!.map((a, i) => <li key={i}>{a}</li>)}
            </ul>
          </div>
        )}

          </>
        ) : (
          <Simulation
            modelId={model.id}
            artefact={artefact}
            estRegression={estRegression}
            cible={r.cible}
            delay={250}
          />
        )}

        <div className="text-center text-xs text-gray-400 dark:text-gray-600 pt-2">
          Créé le {new Date(model.created_at).toLocaleString("fr-FR")} — budget {r.budget_secondes} s
        </div>
      </div>
    </div>
  );
}
