import type { Metadata } from "next";
import "./globals.css";
import { Geist, Google_Sans, Roboto, Roboto_Mono } from "next/font/google";
import { cn } from "@/lib/utils";
import NgrokFetchPatch from "./components/NgrokFetchPatch";

// Chargées via next/font plutôt que par un <link> vers fonts.googleapis.com :
// les fichiers sont auto-hébergés (aucune requête vers Google au runtime, donc
// pas de fuite d'IP visiteur) et le rendu ne subit pas de décalage de mise en
// page. Un <link> dans un composant déclenchait `@next/next/no-page-custom-font`.
const geist = Geist({ subsets: ["latin"], variable: "--font-sans" });
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
  title: "SALI AI",
  description: "SALI AI — From raw data to published insights",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="fr"
      className={cn(
        "font-sans",
        geist.variable,
        googleSans.variable,
        roboto.variable,
        robotoMono.variable,
      )}
    >
      <body
        suppressHydrationWarning
        style={{
          background: "#131314",
          color: "#e3e3e3",
          fontFamily: "var(--font-roboto), sans-serif",
        }}
      >
        <NgrokFetchPatch />
        {children}
      </body>
    </html>
  );
}
