import { useEffect } from "react";
import { useLocation } from "react-router-dom";

const BRAND = "AnomalyDetect";

/** Prefixo de rota → nome da tela. O mais específico vem primeiro. */
const SCREENS: [RegExp, string][] = [
  [/^\/$/, "Painel"],
  [/^\/welcome/, "Conectar computador"],
  [/^\/machines\/\d+/, "Computador"],
  [/^\/machines/, "Computadores"],
  [/^\/anomalies\/\d+/, "Aviso"],
  [/^\/anomalies/, "Avisos"],
  [/^\/pergunte/, "Pergunte"],
  [/^\/account/, "Sua conta"],
  [/^\/pesquisa/, "Pesquisa"],
  [/^\/demonstracao/, "Demonstração"],
  [/^\/estudo/, "Estudo de compreensão"],
  [/^\/login/, "Entrar"],
  [/^\/register/, "Criar conta"],
  [/^\/compartilhado/, "Diagnóstico compartilhado"],
];

/** "Painel · AnomalyDetect"; `name` (de um computador, de um aviso) tem precedência. */
export function pageTitle(pathname: string, name?: string | null) {
  const screen = name || SCREENS.find(([pattern]) => pattern.test(pathname))?.[1];
  return screen ? `${screen} · ${BRAND}` : BRAND;
}

/**
 * Põe o nome do item no título quando ele chega (o computador, o aviso).
 * Depende também do endereço: de um aviso para outro do mesmo tipo o nome
 * não muda, mas o AppShell acabou de trocar o título pelo genérico.
 */
export function useDocumentTitle(name?: string | null) {
  const { pathname } = useLocation();
  useEffect(() => {
    if (name) document.title = pageTitle(pathname, name);
  }, [name, pathname]);
}
