import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { metaApi } from "../services/api";
import { useAuth } from "./AuthContext";
import type { Policy } from "../types";

/**
 * Os números que descrevem como o sistema trabalha, vindos do servidor.
 *
 * Carrega quando alguém entra, não quando a página abre: o endpoint exige
 * login, e buscar antes devolvia 401 nas telas públicas.
 *
 * Falha em silêncio de propósito: as frases que dependem destes números somem
 * sozinhas (`fillPolicy` devolve nulo) — melhor uma frase a menos que um número errado.
 */
const PolicyContext = createContext<Policy | null>(null);

export function PolicyProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [policy, setPolicy] = useState<Policy | null>(null);
  const userId = user?.id ?? null;

  useEffect(() => {
    if (userId === null) {
      setPolicy(null);
      return;
    }
    let alive = true;
    metaApi
      .policy()
      .then((res) => alive && setPolicy(res.data))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [userId]);

  return <PolicyContext.Provider value={policy}>{children}</PolicyContext.Provider>;
}

export function usePolicy(): Policy | null {
  return useContext(PolicyContext);
}
