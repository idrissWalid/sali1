# Interface Next.js

Interface principale de Sali, construite avec Next.js 16, React 19, TypeScript
et Tailwind CSS 4.

## Lancement

```powershell
Copy-Item .env.example .env.local
npm ci
npm run dev
```

L'application est disponible sur http://localhost:3000 et attend l'API définie
par `NEXT_PUBLIC_API_URL`.

## Validation

```powershell
npm run lint
npm run build
npm start
```

Les variables préfixées par `NEXT_PUBLIC_` sont intégrées au bundle navigateur
et ne doivent jamais contenir de véritable secret.
