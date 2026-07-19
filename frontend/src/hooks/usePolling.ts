import { useEffect } from "react";

/**
 * Executa `callback` imediatamente e depois a cada `intervalMs`.
 * Quando o callback muda (ex: filtro alterado, se memoizado com useCallback
 * e o filtro nas dependências), a busca dispara NA HORA e o timer reinicia.
 *
 * Importante: o callback DEVE vir de useCallback — uma função inline nova a
 * cada render reiniciaria o polling continuamente.
 */
export function usePolling(callback: () => void, intervalMs: number, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    callback();
    const id = setInterval(callback, intervalMs);
    return () => clearInterval(id);
  }, [callback, intervalMs, enabled]);
}
