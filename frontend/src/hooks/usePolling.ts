import { useCallback, useEffect, useRef, useState } from "react";

export interface PollingState {
  /** Primeira carga ainda não terminou. Use para mostrar esqueleto. */
  initialLoading: boolean;
  /** Erro da última tentativa. `null` quando a última tentativa deu certo. */
  error: unknown | null;
  /** Momento da última carga bem-sucedida. */
  lastUpdatedAt: number | null;
  /** Força uma busca agora (botão "tentar de novo"). */
  refresh: () => void;
}

/**
 * Executa `callback` na hora e a cada `intervalMs`, informando estado de
 * carga e de erro.
 *
 * O ponto principal: se o callback rejeitar, o erro é capturado e devolvido
 * em `error` em vez de virar uma promise não tratada. Antes, o backend cair
 * fazia o polling falhar em silêncio e a tela continuar exibindo os números
 * antigos como se fossem atuais.
 *
 * `callback` DEVE vir de useCallback — uma função nova a cada render
 * reiniciaria o polling continuamente.
 */
export function usePolling(callback: () => Promise<void> | void, intervalMs: number, enabled = true): PollingState {
  const [initialLoading, setInitialLoading] = useState(true);
  const [error, setError] = useState<unknown | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [tick, setTick] = useState(0);
  const doneFirst = useRef(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const run = useCallback(async () => {
    try {
      await callback();
      if (!alive.current) return;
      setError(null);
      setLastUpdatedAt(Date.now());
    } catch (err) {
      if (!alive.current) return;
      setError(err);
    } finally {
      if (alive.current && !doneFirst.current) {
        doneFirst.current = true;
        setInitialLoading(false);
      }
    }
  }, [callback]);

  useEffect(() => {
    if (!enabled) {
      setInitialLoading(false);
      return;
    }
    run();
    // Aba em segundo plano não precisa de dado novo: três laços de polling
    // mais o WebSocket batendo no servidor enquanto ninguém olha gastam
    // bateria do celular e fila do backend à toa. Ao voltar, busca na hora.
    const id = setInterval(() => {
      if (!document.hidden) run();
    }, intervalMs);
    const aoVoltar = () => {
      if (!document.hidden) run();
    };
    document.addEventListener("visibilitychange", aoVoltar);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", aoVoltar);
    };
  }, [run, intervalMs, enabled, tick]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  return { initialLoading, error, lastUpdatedAt, refresh };
}
