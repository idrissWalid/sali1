/**
 * Déclaration minimale de `plotly.js-dist-min`, qui n'embarque pas ses types.
 *
 * Les types officiels (`@types/plotly.js`) tirent la définition complète de la
 * bibliothèque pour deux fonctions utilisées dans un seul composant : on décrit
 * ici la surface réellement appelée (voir app/components/PlotlyChart.tsx).
 */
declare module "plotly.js-dist-min" {
  export function react(
    node: HTMLElement,
    data: unknown[],
    layout?: unknown,
    config?: unknown,
  ): Promise<unknown>;

  export function purge(node: HTMLElement): void;

  const Plotly: { react: typeof react; purge: typeof purge };
  export default Plotly;
}
