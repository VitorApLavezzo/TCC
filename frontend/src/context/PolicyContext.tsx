import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { metaApi } from "../services/api";
import type { Policy } from "../types";

/**
 * Os números que descrevem como o sistema trabalha, vindos do servidor.
 *
 * Antes estavam escritos à mão no texto de cada tela, e divergiam: quatro
 * telas afirmavam "a cada 30 segundos" numa coleta que vai de 10 a 60 conforme
 * o que está acontecendo, e a frase do aprendizado precisava ser editada aqui
 * toda vez que a régua mudava no servidor.
 *
 * Carrega uma vez por sessão. Falha em silêncio de propósito: nenhuma frase
 * que depende destes números é essencial, e todas somem sozinhas quando a
 * política não chega (`fillPolicy` devolve nulo) — melhor uma frase a menos
 * que um número errado.
 */
const PolicyContext = createContext<Policy | null>(null);

export function PolicyProvider({ children }: { children: ReactNode }) {
  const [policy, setPolicy] = useState<Policy | null>(null);

  useEffect(() => {
    let vivo = true;
    metaApi
      .policy()
      .then((res) => vivo && setPolicy(res.data))
      .catch(() => undefined);
    return () => {
      vivo = false;
    };
  }, []);

  return <PolicyContext.Provider value={policy}>{children}</PolicyContext.Provider>;
}

export function usePolicy(): Policy | null {
  return useContext(PolicyContext);
}
