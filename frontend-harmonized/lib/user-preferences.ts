export type InterfaceLanguage = "fr" | "en";

export type UserPreferences = {
  language: InterfaceLanguage;
  textAnimations: boolean;
};

export const USER_PREFERENCES_KEY = "sali-ai-preferences";
export const USER_PREFERENCES_EVENT = "sali-ai-preferences-change";

export const DEFAULT_USER_PREFERENCES: UserPreferences = {
  language: "fr",
  textAnimations: true,
};

export function readUserPreferences(): UserPreferences {
  if (typeof window === "undefined") return DEFAULT_USER_PREFERENCES;
  try {
    const saved = JSON.parse(localStorage.getItem(USER_PREFERENCES_KEY) ?? "{}") as Partial<UserPreferences>;
    return {
      language: saved.language === "en" ? "en" : "fr",
      textAnimations: saved.textAnimations !== false,
    };
  } catch {
    return DEFAULT_USER_PREFERENCES;
  }
}

export function saveUserPreferences(preferences: UserPreferences): void {
  localStorage.setItem(USER_PREFERENCES_KEY, JSON.stringify(preferences));
  document.documentElement.lang = preferences.language;
  document.documentElement.dataset.textAnimations = preferences.textAnimations ? "on" : "off";
  window.dispatchEvent(new CustomEvent(USER_PREFERENCES_EVENT, { detail: preferences }));
}
