// URL de base de l'API backend. Centralisée ici pour éviter de recopier
// `process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"` dans chaque
// composant qui appelle l'API.
export const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

// Clé partagée avec le backend (voir backend/.env API_AUTH_KEY). Vide en
// développement local : l'authentification est alors désactivée côté backend,
// cette clé n'est donc pas requise. À définir avant tout déploiement hors
// localhost — voir README. Injectée automatiquement sur chaque requête vers
// l'API par NgrokFetchPatch (patch global de `fetch`, monté dans layout.tsx).
export const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";
