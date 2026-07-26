"use client";

import { useEffect } from "react";
import { API_URL, API_KEY } from "@/lib/api";

/**
 * Patch global de `fetch` pour toute requête vers l'API backend :
 *  - ajoute l'en-tête d'authentification X-API-Key si NEXT_PUBLIC_API_KEY est
 *    défini (voir backend/.env API_AUTH_KEY ; vide en dev local, l'auth est
 *    alors désactivée côté backend et cet en-tête n'a aucun effet) ;
 *  - ajoute "ngrok-skip-browser-warning" quand l'API est exposée via ngrok
 *    (l'offre gratuite affiche sinon une page d'avertissement HTML à la place
 *    de la réponse, pour toute requête venant d'un navigateur).
 */
export default function NgrokFetchPatch() {
  useEffect(() => {
    const isNgrok = API_URL.includes("ngrok");
    if (!API_KEY && !isNgrok) return;

    const originalFetch = window.fetch;
    window.fetch = (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.startsWith(API_URL)) {
        const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
        if (API_KEY) headers.set("X-API-Key", API_KEY);
        if (isNgrok) headers.set("ngrok-skip-browser-warning", "true");
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
