import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Estado que mora na URL: sobrevive ao recarregar e pode ser compartilhado.
 * O valor padrão nunca é escrito na barra de endereço.
 */
export function useUrlState<T extends string | number | boolean>(
  key: string,
  fallback: T
): [T, (value: T | ((previous: T) => T)) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get(key);

  let value = fallback;
  if (raw !== null) {
    if (typeof fallback === "number") value = (Number(raw) as T) ?? fallback;
    else if (typeof fallback === "boolean") value = (raw === "1") as T;
    else value = raw as T;
  }

  const set = useCallback(
    (next: T | ((previous: T) => T)) => {
      setParams(
        (current) => {
          const nextParams = new URLSearchParams(current);
          // Aceita valor ou função, como useState: `setPage((p) => p + 1)`.
          const previous = current.get(key);
          const currentTyped = (previous === null
            ? fallback
            : typeof fallback === "number"
              ? (Number(previous) as T)
              : typeof fallback === "boolean"
                ? ((previous === "1") as T)
                : (previous as T)) as T;
          const finalValue = typeof next === "function" ? (next as (a: T) => T)(currentTyped) : next;
          const isDefault = finalValue === fallback || finalValue === "";
          if (isDefault) nextParams.delete(key);
          else nextParams.set(key, typeof finalValue === "boolean" ? (finalValue ? "1" : "0") : String(finalValue));
          return nextParams;
        },
        // `replace`: cada tecla num filtro não empilha entrada no histórico;
        // Voltar precisa sair da tela, não desfazer caractere por caractere.
        { replace: true }
      );
    },
    [fallback, key, setParams]
  );

  return [value, set];
}
