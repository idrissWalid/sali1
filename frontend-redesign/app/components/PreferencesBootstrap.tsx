"use client";

import { useEffect } from "react";
import { readUserPreferences } from "@/lib/user-preferences";

export default function PreferencesBootstrap() {
  useEffect(() => {
    const preferences = readUserPreferences();
    document.documentElement.lang = preferences.language;
    document.documentElement.dataset.textAnimations = preferences.textAnimations ? "on" : "off";
  }, []);

  return null;
}
