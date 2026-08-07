"use client";

import { useSyncExternalStore } from "react";

/**
 * Thème courant, lu directement depuis l'attribut `data-theme` de <html>.
 *
 * Le thème est piloté par le DOM (l'attribut est posé par le toggle et persiste
 * entre les pages) : c'est donc une source externe à React. Le lire via
 * `useSyncExternalStore` évite le motif « useState + useEffect qui appelle
 * setState au montage », qui déclenche un second rendu en cascade à chaque
 * montage — ce que signale la règle `react-hooks/set-state-in-effect`.
 */

type Theme = "dark" | "light";

/** Clé du thème, à part des autres préférences : elle doit être relue par un
 *  script bloquant AVANT le premier rendu (voir `THEME_BOOTSTRAP_SCRIPT`), donc
 *  sans passer par un JSON à parser. */
export const THEME_STORAGE_KEY = "sali-ai-theme";

export const DEFAULT_THEME: Theme = "dark";

/** Script à exécuter dans `<head>`, avant la peinture.
 *
 *  Sans lui, le thème choisi n'est appliqué qu'après l'hydratation : un
 *  utilisateur en clair verrait l'application s'afficher en sombre à chaque
 *  chargement, puis basculer. Le script est volontairement minuscule et
 *  synchrone — c'est le seul moyen d'agir avant le premier rendu.
 */
export const THEME_BOOTSTRAP_SCRIPT = `(function(){try{var t=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});document.documentElement.setAttribute("data-theme",t==="light"||t==="dark"?t:${JSON.stringify(
  DEFAULT_THEME,
)})}catch(e){document.documentElement.setAttribute("data-theme",${JSON.stringify(
  DEFAULT_THEME,
)})}})()`;

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => observer.disconnect();
}

function getSnapshot(): Theme {
  return (document.documentElement.getAttribute("data-theme") as Theme | null) ?? DEFAULT_THEME;
}

// Rendu serveur : l'attribut n'existe pas encore, on annonce le thème par défaut
// de l'application pour que l'hydratation corresponde au premier rendu client.
// `useSyncExternalStore` relira `getSnapshot` juste après l'hydratation et
// re-rendra si le thème persisté diffère — ce n'est donc pas une désynchro.
function getServerSnapshot(): Theme {
  return DEFAULT_THEME;
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

/** Applique un thème : l'attribut pilote le rendu, le stockage le fait survivre
 *  au rechargement et aux changements de page. Les abonnés sont notifiés par le
 *  MutationObserver, il n'y a donc aucun état React à synchroniser.
 *
 *  Point d'entrée UNIQUE : toute autre écriture de `data-theme` réintroduirait
 *  une seconde source de vérité, et c'est exactement ce qui faisait perdre le
 *  choix de l'utilisateur à chaque retour vers l'espace de travail. */
export function setTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Stockage indisponible (navigation privée, quota) : le thème reste
    // appliqué pour la session en cours, il ne survivra simplement pas.
  }
}

export function toggleTheme(): void {
  setTheme(getSnapshot() === "dark" ? "light" : "dark");
}
