import { useSyncExternalStore } from "react";

/**
 * Idioma da interface. A tradução é por tela: `t(key, ptFallback)` devolve o
 * texto em português quando a chave ainda não foi traduzida.
 */
export type Locale = "pt-BR" | "en";

const DICTIONARY: Record<Locale, Record<string, string>> = {
  "pt-BR": {},
  en: {
    "nav.dashboard": "Dashboard",
    "nav.machines": "Computers",
    "nav.anomalies": "Alerts",
    "nav.ask": "Ask",
    "nav.advanced": "Thesis tools",
    "nav.research": "Research",
    "nav.demo": "Demo",
    "nav.study": "Study",
    "nav.sections": "Sections",
    "nav.account": "Your account",
    "nav.logout": "Sign out",
    "nav.skip": "Skip to content",
    "shell.offline": "Server unreachable",
    "shell.theme.toDark": "Use the dark theme",
    "shell.theme.toLight": "Use the light theme",
    "shell.open": "open",
    "action.retry": "Try again",
    "action.cancel": "Cancel",
    "action.save": "Save",
    "action.search": "Search",
    "action.close": "Close",
    "auth.username": "Username",
    "auth.password": "Password",
    "auth.signIn": "Sign in",
    "auth.signingIn": "Signing in...",
    "auth.createAccount": "Create account",
    "auth.noAccount": "Don't have an account?",
    "auth.haveAccount": "Already have an account?",
    "auth.showPassword": "Show the password",
    "auth.hidePassword": "Hide the password",
  },
};

const STORAGE_KEY = "locale";
let current: Locale = readSaved();
const listeners = new Set<() => void>();

function readSaved(): Locale {
  try {
    return localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "pt-BR";
  } catch {
    return "pt-BR";
  }
}

export function getLocale(): Locale {
  return current;
}

/*
 * O `lang` do documento fica em pt-BR mesmo com o inglês escolhido: só a
 * navegação e as telas de entrada estão traduzidas, e com lang="en" o leitor
 * de tela lia todo o resto, em português, com pronúncia de inglês.
 */
export function setLocale(locale: Locale): void {
  current = locale;
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    /* navegação privativa: a escolha vale só nesta sessão */
  }
  listeners.forEach((fn) => fn());
}

/** Texto da chave no idioma atual; em português, o texto que já está no código. */
export function t(key: string, ptFallback: string): string {
  return DICTIONARY[current][key] ?? ptFallback;
}

export function useLocale(): Locale {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getLocale,
    () => "pt-BR" as Locale
  );
}

/** Traduz reagindo à troca de idioma — use dentro de componente. */
export function useT(): (key: string, ptFallback: string) => string {
  useLocale();
  return t;
}
