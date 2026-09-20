import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Estado que mora na URL, e não dentro do componente.
 *
 * Filtro guardado em `useState` desaparece ao recarregar, não pode ser
 * mandado para ninguém e faz o botão Voltar do navegador sair da página em
 * vez de desfazer o filtro. Na URL, os três problemas somem de uma vez.
 *
 * O valor padrão nunca é escrito na barra de endereço: a URL limpa continua
 * limpa, e só aparece o que a pessoa de fato mudou.
 */
export function useUrlState<T extends string | number | boolean>(
  key: string,
  fallback: T
): [T, (value: T | ((anterior: T) => T)) => void] {
  const [params, setParams] = useSearchParams();
  const bruto = params.get(key);

  let valor = fallback;
  if (bruto !== null) {
    if (typeof fallback === "number") valor = (Number(bruto) as T) ?? fallback;
    else if (typeof fallback === "boolean") valor = (bruto === "1") as T;
    else valor = bruto as T;
  }

  const set = useCallback(
    (novo: T | ((anterior: T) => T)) => {
      setParams(
        (atual) => {
          const proximo = new URLSearchParams(atual);
          // Aceita valor ou função, como useState: `setPagina((p) => p + 1)`
          // é a forma natural de paginar, e sem isso cada chamada precisaria
          // ler o valor atual antes.
          const anterior = atual.get(key);
          const atualTipado = (anterior === null
            ? fallback
            : typeof fallback === "number"
              ? (Number(anterior) as T)
              : typeof fallback === "boolean"
                ? ((anterior === "1") as T)
                : (anterior as T)) as T;
          const valorFinal = typeof novo === "function" ? (novo as (a: T) => T)(atualTipado) : novo;
          const igualAoPadrao = valorFinal === fallback || valorFinal === "";
          if (igualAoPadrao) proximo.delete(key);
          else proximo.set(key, typeof valorFinal === "boolean" ? (valorFinal ? "1" : "0") : String(valorFinal));
          return proximo;
        },
        // `replace`: mexer num filtro não deve empilhar uma entrada no
        // histórico a cada tecla; Voltar precisa sair da tela, não desfazer
        // caractere por caractere.
        { replace: true }
      );
    },
    [fallback, key, setParams]
  );

  return [valor, set];
}
