import { useEffect } from "react";
import { useLocation } from "react-router-dom";

const MARCA = "AnomalyDetect";

/** Prefixo de rota → nome da tela. O mais específico vem primeiro. */
const TELAS: [RegExp, string][] = [
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

/** "Painel · AnomalyDetect"; `nome` (de um computador, de um aviso) tem precedência. */
export function pageTitle(pathname: string, nome?: string | null) {
  const tela = nome || TELAS.find(([padrao]) => padrao.test(pathname))?.[1];
  return tela ? `${tela} · ${MARCA}` : MARCA;
}

/**
 * Põe o nome do item no título quando ele chega (o computador, o aviso).
 * Depende também do endereço: de um aviso para outro do mesmo tipo o nome
 * não muda, mas o AppShell acabou de trocar o título pelo genérico.
 */
export function useDocumentTitle(nome?: string | null) {
  const { pathname } = useLocation();
  useEffect(() => {
    if (nome) document.title = pageTitle(pathname, nome);
  }, [nome, pathname]);
}
