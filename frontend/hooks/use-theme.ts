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

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
  return () => observer.disconnect();
}

function getSnapshot(): Theme {
  return (document.documentElement.getAttribute("data-theme") as Theme | null) ?? "dark";
}

// Rendu serveur : l'attribut n'existe pas encore, on annonce le thème par défaut
// de l'application pour que l'hydratation corresponde au premier rendu client.
function getServerSnapshot(): Theme {
  return "dark";
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}

/** Bascule le thème en écrivant sur <html> ; les abonnés sont notifiés par le
 *  MutationObserver, il n'y a donc aucun état React à synchroniser. */
export function toggleTheme(): void {
  const suivant: Theme = getSnapshot() === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", suivant);
}
