"use client";

/**
 * Repli Plotly pour les deux formes que Recharts ne trace pas : la boîte à
 * moustaches et la carte de chaleur.
 *
 * Plotly pèse plusieurs mégaoctets : il est importé dynamiquement à l'intérieur
 * de l'effet, donc téléchargé seulement quand un graphique de ce type arrive
 * réellement dans la conversation. Aucun wrapper React n'est utilisé — la
 * bibliothèque pilote un nœud DOM directement, ce qui évite une dépendance de
 * plus et ses questions de compatibilité de version.
 *
 * Plotly ne comprend pas `var(--viz-N)` : les couleurs sont résolues en valeurs
 * calculées, et re-résolues au changement de thème.
 */

import { useEffect, useRef, useState } from "react";
import type { ChartSpec } from "./ChatChart";

type PlotlyModule = {
  react: (n: HTMLElement, d: unknown[], l: unknown, c: unknown) => Promise<unknown>;
  purge: (n: HTMLElement) => void;
};

const VARIABLES_SERIES = ["--viz-1", "--viz-2", "--viz-3", "--viz-4", "--viz-5", "--viz-6", "--viz-7", "--viz-8"];

function lireCouleurs() {
  const style = getComputedStyle(document.documentElement);
  const valeur = (nom: string, defaut: string) => style.getPropertyValue(nom).trim() || defaut;
  return {
    series: VARIABLES_SERIES.map((nom, i) => valeur(nom, ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"][i])),
    encre: valeur("--text-main", "#f1f3f8"),
    attenue: valeur("--text-muted", "#a3aaba"),
    grille: valeur("--viz-grid", "rgba(187,198,224,0.11)"),
    surface: valeur("--surface-panel", "#121212"),
  };
}

export default function PlotlyChart({ spec, hauteur }: { spec: ChartSpec; hauteur: number }) {
  const noeud = useRef<HTMLDivElement>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  // Le basculement de thème réécrit `data-theme` sur <html> : on s'y abonne pour
  // recalculer les couleurs, que Plotly a figées en dur au rendu précédent.
  const [theme, setTheme] = useState(0);

  useEffect(() => {
    const observateur = new MutationObserver(() => setTheme(t => t + 1));
    observateur.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observateur.disconnect();
  }, []);

  useEffect(() => {
    let annule = false;
    const cible = noeud.current;
    if (!cible) return;

    (async () => {
      try {
        const bibliotheque = await import("plotly.js-dist-min");
        if (annule || !noeud.current) return;
        const Plotly = (bibliotheque.default ?? bibliotheque) as unknown as PlotlyModule;
        const couleurs = lireCouleurs();
        const { traces, layoutSpecifique } = construire(spec, couleurs);

        await Plotly.react(
          noeud.current,
          traces,
          {
            height: hauteur,
            margin: { l: 56, r: 16, t: 8, b: 44 },
            paper_bgcolor: "transparent",
            plot_bgcolor: "transparent",
            font: { color: couleurs.attenue, size: 11, family: "system-ui, -apple-system, 'Segoe UI', sans-serif" },
            xaxis: { title: { text: spec.x.label, font: { color: couleurs.attenue } }, gridcolor: couleurs.grille, zeroline: false },
            yaxis: { title: { text: spec.y.label ?? "", font: { color: couleurs.attenue } }, gridcolor: couleurs.grille, zeroline: false },
            showlegend: false,
            hoverlabel: { bgcolor: couleurs.surface, bordercolor: couleurs.grille, font: { color: couleurs.encre } },
            ...layoutSpecifique,
          },
          { displaylogo: false, responsive: true, displayModeBar: false },
        );
      } catch (exc) {
        if (!annule) setErreur(exc instanceof Error ? exc.message : "Rendu indisponible");
      }
    })();

    return () => {
      annule = true;
      if (cible) {
        import("plotly.js-dist-min")
          .then(m => ((m.default ?? m) as unknown as PlotlyModule).purge(cible))
          .catch(() => undefined);
      }
    };
  }, [spec, hauteur, theme]);

  if (erreur) {
    return (
      <div style={{ height: hauteur, display: "grid", placeItems: "center", color: "var(--text-dim)", fontSize: 12, textAlign: "center", padding: "0 12px" }}>
        Graphique indisponible ({erreur}). Les valeurs restent lisibles via le bouton « Valeurs ».
      </div>
    );
  }

  return <div ref={noeud} style={{ width: "100%", height: hauteur }} />;
}

function construire(spec: ChartSpec, couleurs: ReturnType<typeof lireCouleurs>) {
  if (spec.kind === "heatmap") {
    const cleY = spec.series[0]?.key ?? "y";
    const cleV = spec.data.some(l => "v" in l) ? "v" : "valeur";
    const colonnes = [...new Set(spec.data.map(l => String(l[spec.x.key])))];
    const lignes = [...new Set(spec.data.map(l => String(l[cleY])))];
    const matrice = lignes.map(ligne =>
      colonnes.map(colonne => {
        const trouve = spec.data.find(l => String(l[cleY]) === ligne && String(l[spec.x.key]) === colonne);
        return typeof trouve?.[cleV] === "number" ? (trouve[cleV] as number) : null;
      }),
    );
    return {
      // Une seule teinte, du clair au foncé : une échelle arc-en-ciel invente
      // des ruptures là où la grandeur est continue.
      traces: [{
        type: "heatmap",
        x: colonnes,
        y: lignes,
        z: matrice,
        colorscale: [[0, "#cde2fb"], [0.5, "#3987e5"], [1, "#0d366b"]],
        hovertemplate: "%{y} · %{x} : %{z}<extra></extra>",
        colorbar: { thickness: 10, outlinewidth: 0, tickfont: { color: couleurs.attenue } },
      }],
      layoutSpecifique: {},
    };
  }

  // Boîtes à moustaches : soit les quantiles sont déjà calculés, soit la série
  // brute est fournie et Plotly les calcule.
  const traces = spec.data.map((ligne, i) => {
    const nom = String(ligne[spec.x.key] ?? `Groupe ${i + 1}`);
    const couleur = couleurs.series[i % couleurs.series.length];
    const mediane = ligne["mediane"] ?? ligne["median"];
    if (ligne["q1"] !== undefined && ligne["q3"] !== undefined) {
      return {
        type: "box", name: nom, x: [nom],
        q1: [ligne["q1"]], median: [mediane], q3: [ligne["q3"]],
        lowerfence: [ligne["min"]], upperfence: [ligne["max"]],
        marker: { color: couleur }, line: { width: 1.5 }, fillcolor: couleur, opacity: 0.35,
      };
    }
    const valeurs = spec.series.map(s => ligne[s.key]).filter(v => typeof v === "number");
    return {
      type: "box", name: nom, y: valeurs,
      marker: { color: couleur }, line: { width: 1.5 }, fillcolor: couleur, opacity: 0.35,
      boxpoints: false,
    };
  });

  return { traces, layoutSpecifique: { boxgap: 0.4 } };
}
