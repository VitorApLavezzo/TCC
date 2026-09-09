import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { ConnectionState, getConnection, subscribeConnection } from "../lib/connection";

interface StatusValue extends ConnectionState {
  /** Relógio de 1s — quem mostra "há X" depende dele para reescrever. */
  now: number;
  /** O navegador está sem rede? Distingue "sua internet" de "nosso servidor". */
  online: boolean;
}

const StatusCtx = createContext<StatusValue | null>(null);

export function useStatus() {
  const ctx = useContext(StatusCtx);
  if (!ctx) throw new Error("useStatus precisa estar dentro de <StatusProvider>");
  return ctx;
}

/**
 * Fonte única de verdade sobre "os dados na tela são confiáveis agora?".
 *
 * Toda incerteza da interface — servidor fora, agente parado, leitura velha —
 * é derivada daqui, para as respostas não se contradizerem entre páginas.
 */
export function StatusProvider({ children }: { children: ReactNode }) {
  const [conn, setConn] = useState<ConnectionState>(getConnection);
  const [now, setNow] = useState(() => Date.now());
  const [online, setOnline] = useState(() => navigator.onLine);

  useEffect(() => subscribeConnection(setConn), []);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  return <StatusCtx.Provider value={{ ...conn, now, online }}>{children}</StatusCtx.Provider>;
}
