import type { Metadata } from "next";
import "./globals.css";
import NgrokFetchPatch from "./components/NgrokFetchPatch";

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
    <html lang="fr" className="font-sans">
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
