import { useSyncExternalStore } from "react";

/**
 * Idioma da interface.
 *
 * O sistema nasceu com o português no meio do código, o que é natural num
 * trabalho brasileiro e vira um problema na hora de mostrá-lo para fora.
 * Aqui fica a infraestrutura: um dicionário por idioma, uma função de busca
 * com reserva no português e um seletor que persiste a escolha.
 *
 * A migração é por tela, e não de uma vez: `t("chave")` devolve o texto em
 * português quando a chave ainda não foi traduzida, então nada quebra no
 * meio do caminho.
 */
export type Locale = "pt-BR" | "en";

const DICIONARIO: Record<Locale, Record<string, string>> = {
  "pt-BR": {},
  en: {
    // Navegação e moldura
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
    // Ações recorrentes
    "action.retry": "Try again",
    "action.cancel": "Cancel",
    "action.save": "Save",
    "action.search": "Search",
    "action.close": "Close",
    // Entrar e criar conta
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

const CHAVE_ARMAZENADA = "locale";
let atual: Locale = lerSalvo();
const ouvintes = new Set<() => void>();

function lerSalvo(): Locale {
  try {
    return localStorage.getItem(CHAVE_ARMAZENADA) === "en" ? "en" : "pt-BR";
  } catch {
    return "pt-BR";
  }
}

export function getLocale(): Locale {
  return atual;
}

/*
 * O `lang` do documento fica em pt-BR mesmo com o inglês escolhido: só a
 * navegação e as telas de entrada estão traduzidas, e com lang="en" o leitor
 * de tela lia todo o resto, em português, com pronúncia de inglês.
 */
export function setLocale(locale: Locale): void {
  atual = locale;
  try {
    localStorage.setItem(CHAVE_ARMAZENADA, locale);
  } catch {
    /* navegação privativa: a escolha vale só nesta sessão */
  }
  ouvintes.forEach((fn) => fn());
}

/** Texto da chave no idioma atual; em português, o texto que já está no código. */
export function t(chave: string, padraoEmPortugues: string): string {
  return DICIONARIO[atual][chave] ?? padraoEmPortugues;
}

export function useLocale(): Locale {
  return useSyncExternalStore(
    (ouvir) => {
      ouvintes.add(ouvir);
      return () => ouvintes.delete(ouvir);
    },
    getLocale,
    () => "pt-BR" as Locale
  );
}

/** Traduz reagindo à troca de idioma — use dentro de componente. */
export function useT(): (chave: string, padraoEmPortugues: string) => string {
  useLocale();
  return t;
}
