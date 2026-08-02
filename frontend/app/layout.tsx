import type { Metadata } from "next";
import "./globals.css";
import { Caprasimo, Figtree, Google_Sans, Roboto, Roboto_Mono } from "next/font/google";
import { cn } from "@/lib/utils";
import { DEFAULT_THEME, THEME_BOOTSTRAP_SCRIPT } from "@/hooks/use-theme";
import NgrokFetchPatch from "./components/NgrokFetchPatch";
import PreferencesBootstrap from "./components/PreferencesBootstrap";

// Chargées via next/font plutôt que par un <link> vers fonts.googleapis.com :
// les fichiers sont auto-hébergés (aucune requête vers Google au runtime, donc
// pas de fuite d'IP visiteur) et le rendu ne subit pas de décalage de mise en
// page. Un <link> dans un composant déclenchait `@next/next/no-page-custom-font`.
const figtree = Figtree({ subsets: ["latin"], variable: "--font-figtree" });
const caprasimo = Caprasimo({ subsets: ["latin"], weight: "400", variable: "--font-brand" });
const googleSans = Google_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-google-sans",
  // next/font ne connaît pas les métriques de Google Sans et échoue à calculer
  // la police de repli anti-CLS (« Failed to find font override values »).
  // On désactive ce calcul : la police se charge normalement, seul l'ajustement
  // automatique du fallback est abandonné.
  adjustFontFallback: false,
});
const roboto = Roboto({
  subsets: ["latin"],
  weight: ["300", "400", "500"],
  variable: "--font-roboto",
});
const robotoMono = Roboto_Mono({ subsets: ["latin"], variable: "--font-roboto-mono" });

export const metadata: Metadata = {
  title: "Sali AI",
  description: "Sali AI — From raw data to published insights",
  icons: {
    icon: [{ url: "/brand/sali-favicon.svg", type: "image/svg+xml" }],
    apple: "/brand/sali-app-icon.svg",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="fr"
      // Rendu serveur avec le thème par défaut ; le script ci-dessous le
      // remplace par le thème persisté avant la peinture. `suppressHydration
      // Warning` couvre cet écart volontaire entre HTML serveur et DOM client.
      data-theme={DEFAULT_THEME}
      suppressHydrationWarning
      className={cn(
        "font-sans",
        figtree.variable,
        caprasimo.variable,
        googleSans.variable,
        roboto.variable,
        robotoMono.variable,
      )}
    >
      <head>
        {/* Avant tout rendu : sans ce script, un utilisateur en thème clair voit
            l'application s'afficher en sombre puis basculer à chaque chargement. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
      </head>
      <body
        suppressHydrationWarning
        style={{
          // Suivent le thème au lieu d'être figés en sombre : ces valeurs
          // s'appliquent avant la feuille de styles et provoquaient un flash
          // sombre systématique en mode clair.
          background: "var(--bg-app)",
          color: "var(--text-main)",
          fontFamily: "var(--font-figtree), sans-serif",
        }}
      >
        <NgrokFetchPatch />
        <PreferencesBootstrap />
        {children}
      </body>
    </html>
  );
}
