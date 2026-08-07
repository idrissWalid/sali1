"use client";

/**
 * Rendu d'un graphique émis par le backend (`emit_chart`, voir
 * backend/app/services/sandbox_charts.py).
 *
 * Recharts couvre les formes courantes ; boxplot et heatmap, qu'il ne sait pas
 * tracer, partent vers Plotly chargé à la demande (voir PlotlyChart.tsx) — la
 * bibliothèque lourde n'est jamais téléchargée pour un simple histogramme.
 *
 * Les couleurs sont des variables CSS (`var(--viz-N)`) posées directement dans
 * les attributs SVG : le basculement clair/sombre est alors purement CSS, sans
 * re-rendu ni lecture du thème en JavaScript.
 *
 * Trois règles structurent tout le fichier :
 *   1. une légende dès deux séries (jamais pour une seule — le titre la nomme) ;
 *   2. les étiquettes de valeur sont rares et placées hors de la marque, jamais
 *      une valeur sur chaque point ;
 *   3. toute valeur est atteignable sans survol, via la vue tableau — c'est
 *      aussi ce qui rachète les trois teintes claires sous 3:1 en thème clair.
 */

import { lazy, Suspense, useMemo, useState } from "react";
import {
  Area, Bar, CartesianGrid, Cell, ComposedChart, Legend, Line, Pie, PieChart,
  ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, LabelList,
} from "recharts";
import { Table2, ChartColumn } from "lucide-react";

const PlotlyChart = lazy(() => import("./PlotlyChart"));

export interface ChartSpec {
  v?: number;
  kind: "bar" | "column" | "line" | "area" | "scatter" | "pie" | "box" | "heatmap" | "stat";
  title?: string | null;
  note?: string | null;
  x: { key: string; label: string; type: "category" | "number" | "time" };
  y: { label?: string | null; format?: "number" | "percent" | "currency" };
  series: { key: string; label: string }[];
  band?: { key: string; label: string } | null;
  data: Record<string, unknown>[];
  stacked?: boolean;
  emphasis?: string | null;
  reductions?: string[];
}

// Ordre figé des slots : la 3ᵉ série prend toujours --viz-3, y compris si la 2ᵉ
// disparaît. Une couleur suit une entité, jamais son rang à l'écran.
const SERIES_COLORS = [
  "var(--viz-1)", "var(--viz-2)", "var(--viz-3)", "var(--viz-4)",
  "var(--viz-5)", "var(--viz-6)", "var(--viz-7)", "var(--viz-8)",
];

const GRID = "var(--viz-grid)";
const AXIS = "var(--viz-axis)";
const INK_MUTED = "var(--text-muted)";
const SURFACE = "var(--viz-surface)";
const CONTEXT = "var(--viz-context)";

const HAUTEUR = 280;
const MAX_ETIQUETTES_DIRECTES = 8;   // au-delà, l'axe et l'infobulle suffisent
const LONGUEUR_LIBELLE = 18;

/* ── Formatage ────────────────────────────────────────────────────────────── */

const compact = new Intl.NumberFormat("fr-FR", { notation: "compact", maximumFractionDigits: 1 });
const complet = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 });

function formaterValeur(valeur: unknown, format?: string, court = false): string {
  if (valeur === null || valeur === undefined) return "—";
  if (Array.isArray(valeur)) {
    return valeur.map(v => formaterValeur(v, format, court)).join(" – ");
  }
  if (typeof valeur !== "number") return String(valeur);
  const texte = court ? compact.format(valeur) : complet.format(valeur);
  return format === "percent" ? `${texte} %` : texte;
}

function raccourcir(texte: string): string {
  return texte.length > LONGUEUR_LIBELLE ? `${texte.slice(0, LONGUEUR_LIBELLE - 1)}…` : texte;
}

/** Abrège une date ISO : jour/mois si tout tient dans une année, mois/année sinon. */
function formateurDate(donnees: Record<string, unknown>[], cle: string) {
  const annees = new Set(
    donnees
      .map(d => String(d[cle] ?? ""))
      .filter(v => /^\d{4}-\d{2}/.test(v))
      .map(v => v.slice(0, 4)),
  );
  const memeAnnee = annees.size <= 1;
  return (valeur: unknown) => {
    const texte = String(valeur ?? "");
    if (!/^\d{4}-\d{2}/.test(texte)) return raccourcir(texte);
    const [annee, mois, jour] = texte.split("-");
    return memeAnnee && jour ? `${jour}/${mois}` : `${mois}/${annee.slice(2)}`;
  };
}

/* ── Infobulle ────────────────────────────────────────────────────────────── */

interface EntreeInfobulle {
  name?: string;
  value?: unknown;
  color?: string;
  dataKey?: string | number;
}

function Infobulle({
  active, payload, label, spec, formaterAbscisse,
}: {
  active?: boolean;
  payload?: EntreeInfobulle[];
  label?: unknown;
  spec: ChartSpec;
  formaterAbscisse: (v: unknown) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: "var(--surface-panel)",
        border: "1px solid var(--border-color)",
        borderRadius: 10,
        padding: "8px 10px",
        boxShadow: "var(--shadow-panel)",
        fontSize: 12,
      }}
    >
      <div style={{ color: INK_MUTED, marginBottom: 6 }}>{formaterAbscisse(label)}</div>
      {payload.map((entree, i) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 2 }}>
          <span
            aria-hidden
            style={{
              width: 8, height: 8, borderRadius: 2,
              background: entree.color, flexShrink: 0,
            }}
          />
          {/* Le texte porte l'encre du thème, jamais la couleur de la série :
              une teinte claire est illisible en typographie sur la surface. */}
          <span style={{ color: "var(--text-main)" }}>{entree.name}</span>
          <span style={{ color: "var(--text-main)", marginLeft: "auto", fontVariantNumeric: "tabular-nums" }}>
            {formaterValeur(entree.value, spec.y.format)}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ── Vue tableau ──────────────────────────────────────────────────────────── */

function VueTableau({ spec }: { spec: ChartSpec }) {
  return (
    <div style={{ maxHeight: HAUTEUR, overflow: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr>
            <th style={celluleEntete}>{spec.x.label}</th>
            {spec.series.map(s => (
              <th key={s.key} style={{ ...celluleEntete, textAlign: "right" }}>{s.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {spec.data.map((ligne, i) => (
            <tr key={i}>
              <td style={cellule}>{String(ligne[spec.x.key] ?? "—")}</td>
              {spec.series.map(s => (
                <td key={s.key} style={{ ...cellule, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                  {formaterValeur(ligne[s.key], spec.y.format)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const celluleEntete: React.CSSProperties = {
  textAlign: "left",
  padding: "6px 8px",
  color: INK_MUTED,
  fontWeight: 600,
  borderBottom: "1px solid var(--border-color)",
  position: "sticky",
  top: 0,
  background: "var(--viz-surface)",
};

const cellule: React.CSSProperties = {
  padding: "5px 8px",
  color: "var(--text-main)",
  borderBottom: "1px solid var(--border-muted)",
};

/* ── Tuile de statistique ─────────────────────────────────────────────────── */

function Tuile({ spec }: { spec: ChartSpec }) {
  const ligne = spec.data[0] ?? {};
  const serie = spec.series[0];
  return (
    <div style={{ padding: "6px 2px 2px" }}>
      <div style={{ color: INK_MUTED, fontSize: 12 }}>
        {String(ligne[spec.x.key] ?? serie?.label ?? "")}
      </div>
      {/* Chiffres proportionnels : `tabular-nums` desserre les grands nombres. */}
      <div style={{ color: "var(--text-main)", fontSize: 32, fontWeight: 600, lineHeight: 1.2 }}>
        {formaterValeur(ligne[serie?.key], spec.y.format)}
      </div>
      {spec.y.label && (
        <div style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 2 }}>{spec.y.label}</div>
      )}
    </div>
  );
}

/* ── Composant principal ──────────────────────────────────────────────────── */

export default function ChatChart({ spec }: { spec: ChartSpec }) {
  const [tableau, setTableau] = useState(false);

  const couleurs = useMemo(() => {
    const map: Record<string, string> = {};
    spec.series.forEach((s, i) => {
      // Mode emphase : une seule série porte une teinte, les autres passent au
      // gris de contexte. C'est la forme juste quand une série est le sujet.
      map[s.key] = spec.emphasis && s.key !== spec.emphasis
        ? CONTEXT
        : SERIES_COLORS[i % SERIES_COLORS.length];
    });
    return map;
  }, [spec.series, spec.emphasis]);

  const formaterAbscisse = useMemo(
    () => spec.x.type === "time"
      ? formateurDate(spec.data, spec.x.key)
      : (v: unknown) => raccourcir(String(v ?? "")),
    [spec.data, spec.x.key, spec.x.type],
  );

  const rendable = spec.kind === "box" || spec.kind === "heatmap"
    ? "plotly"
    : spec.kind === "stat" ? "tuile" : "recharts";

  return (
    <figure
      style={{
        margin: "12px 0 0",
        padding: "14px 14px 10px",
        background: SURFACE,
        border: "1px solid var(--border-color)",
        borderRadius: 12,
      }}
    >
      <figcaption style={{ display: "flex", alignItems: "start", gap: 10, marginBottom: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {spec.title && (
            <div style={{ color: "var(--text-main)", fontSize: 13, fontWeight: 600, lineHeight: 1.35 }}>
              {spec.title}
            </div>
          )}
          {spec.y.label && spec.kind !== "stat" && (
            <div style={{ color: "var(--text-dim)", fontSize: 11, marginTop: 2 }}>{spec.y.label}</div>
          )}
        </div>
        {rendable !== "tuile" && (
          <button
            type="button"
            onClick={() => setTableau(t => !t)}
            title={tableau ? "Afficher le graphique" : "Afficher les valeurs"}
            aria-pressed={tableau}
            style={{
              display: "flex", alignItems: "center", gap: 5,
              padding: "4px 8px", flexShrink: 0,
              background: "transparent",
              border: "1px solid var(--border-color)",
              borderRadius: 7, cursor: "pointer",
              color: INK_MUTED, fontSize: 11,
            }}
          >
            {tableau
              ? <><ChartColumn size={13} /> Graphique</>
              : <><Table2 size={13} /> Valeurs</>}
          </button>
        )}
      </figcaption>

      {tableau ? (
        <VueTableau spec={spec} />
      ) : rendable === "tuile" ? (
        <Tuile spec={spec} />
      ) : rendable === "plotly" ? (
        <Suspense fallback={<Attente />}>
          <PlotlyChart spec={spec} hauteur={HAUTEUR} />
        </Suspense>
      ) : (
        <div style={{ width: "100%", height: HAUTEUR }}>
          <ResponsiveContainer>
            {rendreGraphique(spec, couleurs, formaterAbscisse)}
          </ResponsiveContainer>
        </div>
      )}

      {(spec.note || spec.reductions?.length) && (
        <div style={{ color: "var(--text-dim)", fontSize: 11, marginTop: 8, lineHeight: 1.5 }}>
          {spec.note}
          {spec.note && spec.reductions?.length ? " · " : ""}
          {spec.reductions?.join(" · ")}
        </div>
      )}
    </figure>
  );
}

function Attente() {
  return (
    <div style={{ height: HAUTEUR, display: "grid", placeItems: "center", color: "var(--text-dim)", fontSize: 12 }}>
      Chargement du graphique…
    </div>
  );
}

/* ── Assemblage Recharts ──────────────────────────────────────────────────── */

function rendreGraphique(
  spec: ChartSpec,
  couleurs: Record<string, string>,
  formaterAbscisse: (v: unknown) => string,
) {
  const horizontal = spec.kind === "bar";
  const multiSeries = spec.series.length > 1 || Boolean(spec.band);
  const etiquetteDirecte =
    spec.series.length === 1 && spec.data.length <= MAX_ETIQUETTES_DIRECTES;

  const infobulle = (
    <Tooltip
      cursor={{ fill: "var(--accent-soft)", stroke: AXIS }}
      content={<Infobulle spec={spec} formaterAbscisse={formaterAbscisse} />}
    />
  );

  const legende = multiSeries ? (
    <Legend
      verticalAlign="bottom"
      height={26}
      iconType="circle"
      iconSize={8}
      formatter={(valeur) => (
        <span style={{ color: INK_MUTED, fontSize: 11 }}>{valeur}</span>
      )}
    />
  ) : null;

  // En barres horizontales les rôles s'échangent : l'axe vertical porte les
  // catégories et l'axe horizontal les valeurs. Les deux axes sont décrits ici
  // une seule fois, chacun sachant se retourner.
  const axeY = (
    <YAxis
      type={horizontal ? "category" : "number"}
      dataKey={horizontal ? spec.x.key : undefined}
      tickFormatter={horizontal
        ? (v: unknown) => formaterAbscisse(v)
        : (v: number) => formaterValeur(v, spec.y.format, true)}
      tick={{ fill: INK_MUTED, fontSize: 11 }}
      tickLine={false}
      axisLine={{ stroke: AXIS }}
      width={horizontal ? 104 : 52}
    />
  );

  const axeX = (
    <XAxis
      type={horizontal ? "number" : "category"}
      dataKey={horizontal ? undefined : spec.x.key}
      tickFormatter={horizontal
        ? (v: number) => formaterValeur(v, spec.y.format, true)
        : formaterAbscisse}
      tick={{ fill: INK_MUTED, fontSize: 11 }}
      tickLine={false}
      axisLine={{ stroke: AXIS }}
      // Recharts espace lui-même les libellés plutôt que de les empiler ; on ne
      // force jamais interval={0}, qui les ferait se chevaucher.
      minTickGap={spec.x.type === "time" ? 28 : 8}
      angle={!horizontal && spec.x.type === "category" && spec.data.length > 6 ? -30 : 0}
      textAnchor={!horizontal && spec.x.type === "category" && spec.data.length > 6 ? "end" : "middle"}
      height={!horizontal && spec.x.type === "category" && spec.data.length > 6 ? 58 : 28}
    />
  );

  // Grille sur le seul axe des valeurs, en trait plein d'un cran au-dessus de la
  // surface : une grille croisée ou pointillée ajoute du bruit, pas de lecture.
  const grille = (
    <CartesianGrid
      stroke={GRID}
      strokeDasharray=""
      vertical={horizontal}
      horizontal={!horizontal}
    />
  );

  if (spec.kind === "pie") {
    const cle = spec.series[0].key;
    const total = spec.data.reduce(
      (somme, ligne) => somme + (typeof ligne[cle] === "number" ? (ligne[cle] as number) : 0), 0,
    );
    return (
      <PieChart>
        <Pie
          data={spec.data}
          dataKey={cle}
          nameKey={spec.x.key}
          innerRadius="45%"
          outerRadius="78%"
          paddingAngle={2}          /* le vide sépare les parts, pas un contour */
          stroke={SURFACE}
          strokeWidth={2}
          isAnimationActive={false}
        >
          {spec.data.map((_, i) => (
            <Cell key={i} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
          ))}
        </Pie>
        <Tooltip
          content={<Infobulle spec={spec} formaterAbscisse={(v) => String(v ?? "")} />}
        />
        <Legend
          verticalAlign="bottom"
          height={30}
          iconType="circle"
          iconSize={8}
          formatter={(valeur, entree) => {
            const valeurBrute = (entree?.payload as Record<string, unknown> | undefined)?.[cle];
            const part = total && typeof valeurBrute === "number"
              ? ` · ${Math.round((valeurBrute / total) * 100)} %`
              : "";
            return <span style={{ color: INK_MUTED, fontSize: 11 }}>{raccourcir(String(valeur))}{part}</span>;
          }}
        />
      </PieChart>
    );
  }

  if (spec.kind === "scatter") {
    return (
      <ScatterChart margin={{ top: 8, right: 12, bottom: 4, left: 0 }}>
        {grille}
        <XAxis
          type="number"
          dataKey={spec.x.key}
          name={spec.x.label}
          tickFormatter={(v: number) => formaterValeur(v, "number", true)}
          tick={{ fill: INK_MUTED, fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: AXIS }}
        />
        <YAxis
          type="number"
          tickFormatter={(v: number) => formaterValeur(v, spec.y.format, true)}
          tick={{ fill: INK_MUTED, fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: AXIS }}
          width={52}
        />
        {infobulle}
        {legende}
        {spec.series.map(s => (
          <Scatter
            key={s.key}
            name={s.label}
            data={spec.data}
            dataKey={s.key}
            fill={couleurs[s.key]}
            /* Anneau à la couleur de la surface : les points restent lisibles
               là où ils se recouvrent, sans contour qui ajoute de l'encre. */
            stroke={SURFACE}
            strokeWidth={2}
            isAnimationActive={false}
          />
        ))}
      </ScatterChart>
    );
  }

  return (
    <ComposedChart
      data={spec.data}
      layout={horizontal ? "vertical" : "horizontal"}
      // Marge réservée du côté où sortent les étiquettes de valeur : la barre la
      // plus haute touche le bord du tracé, son étiquette serait sinon rognée.
      margin={{
        top: etiquetteDirecte && !horizontal ? 20 : 8,
        right: etiquetteDirecte && horizontal ? 48 : 12,
        bottom: 4,
        left: 0,
      }}
    >
      {grille}
      {axeX}
      {axeY}
      {infobulle}
      {legende}

      {/* Bande d'incertitude : tracée en premier pour rester sous les courbes. */}
      {spec.band && (
        <Area
          dataKey={spec.band.key}
          name={spec.band.label}
          stroke="none"
          fill={SERIES_COLORS[1]}
          fillOpacity={0.12}
          isAnimationActive={false}
        />
      )}

      {spec.series.map((s, i) => {
        if (spec.kind === "line" || spec.kind === "area") {
          // L'aire n'est remplie que pour une série unique : deux aires
          // superposées se masquent l'une l'autre, des courbes se lisent.
          const element = spec.kind === "area" && spec.series.length === 1 ? (
            <Area
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={couleurs[s.key]}
              strokeWidth={2}
              fill={couleurs[s.key]}
              fillOpacity={0.1}      /* un lavis, jamais un aplat saturé */
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE }}
              connectNulls
              isAnimationActive={false}
            />
          ) : (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={couleurs[s.key]}
              strokeWidth={2}
              strokeLinecap="round"
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: SURFACE }}
              connectNulls
              isAnimationActive={false}
            />
          );
          return element;
        }

        return (
          <Bar
            key={s.key}
            dataKey={s.key}
            name={s.label}
            fill={couleurs[s.key]}
            stackId={spec.stacked ? "pile" : undefined}
            /* Trait à la couleur de la surface = l'écart de 2px entre segments
               empilés ; ce n'est pas un contour de marque. */
            stroke={spec.stacked ? SURFACE : undefined}
            strokeWidth={spec.stacked ? 2 : 0}
            maxBarSize={24}
            radius={coinsArrondis(horizontal, spec.stacked, i, spec.series.length)}
            isAnimationActive={false}
          >
            {etiquetteDirecte && !spec.stacked && (
              <LabelList
                dataKey={s.key}
                position={horizontal ? "right" : "top"}
                offset={6}
                /* Hors de la marque : une étiquette posée dedans se fait rogner
                   dès que la barre est courte. */
                fill={INK_MUTED}
                fontSize={11}
                formatter={(v: unknown) => formaterValeur(v, spec.y.format, true)}
              />
            )}
          </Bar>
        );
      })}
    </ComposedChart>
  );
}

/** Extrémité arrondie côté valeur, carrée sur la ligne de base. */
function coinsArrondis(
  horizontal: boolean, empile: boolean | undefined, index: number, total: number,
): [number, number, number, number] {
  const arrondi = 4;
  if (empile && index !== total - 1) return [0, 0, 0, 0];
  return horizontal ? [0, arrondi, arrondi, 0] : [arrondi, arrondi, 0, 0];
}
