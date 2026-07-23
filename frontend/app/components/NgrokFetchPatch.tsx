"use client";

import { useEffect } from "react";

/**
 * Ngrok (offre gratuite) affiche une page d'avertissement HTML à la place de la
 * réponse de l'API pour toute requête venant d'un navigateur, sauf si l'en-tête
 * "ngrok-skip-browser-warning" est présent. On patche fetch globalement pour
 * l'ajouter automatiquement sur les requêtes vers l'API.
 */
export default function NgrokFetchPatch() {
  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (!apiUrl || !apiUrl.includes("ngrok")) return;

    const originalFetch = window.fetch;
    window.fetch = (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.startsWith(apiUrl)) {
        const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
        headers.set("ngrok-skip-browser-warning", "true");
        return originalFetch(input, { ...init, headers });
      }
      return originalFetch(input, init);
    };

    return () => {
      window.fetch = originalFetch;
    };
  }, []);

  return null;
}
