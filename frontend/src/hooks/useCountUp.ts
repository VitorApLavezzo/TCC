import { useEffect, useRef, useState } from "react";

/**
 * Número que caminha até o valor novo, em vez de saltar.
 *
 * Não é enfeite: a duração é fixa, então a velocidade do movimento é
 * proporcional ao tamanho do salto — 42% para 45% quase não se mexe, 42%
 * para 91% atravessa a tela. A pessoa percebe a magnitude da mudança antes
 * de ler o número.
 *
 * Só anima quando o valor muda de verdade; a cada ciclo de leitura com o
 * mesmo número, nada se mexe. E respeita quem pediu menos movimento no
 * sistema operacional.
 */
export function useCountUp(alvo: number, duracao = 420): number {
  const [valor, setValor] = useState(alvo);
  const anterior = useRef(alvo);
  const frame = useRef<number>();

  useEffect(() => {
    const de = anterior.current;
    anterior.current = alvo;
    if (de === alvo) return;

    const reduzido = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    // Salto pequeno não merece animação: mexeria por 400ms para andar 1%.
    if (reduzido || Math.abs(alvo - de) < 1.5) {
      setValor(alvo);
      return;
    }

    const inicio = performance.now();
    const passo = (agora: number) => {
      const t = Math.min(1, (agora - inicio) / duracao);
      // Desaceleração no fim: o número "assenta" em vez de parar de súbito.
      const suave = 1 - Math.pow(1 - t, 3);
      setValor(de + (alvo - de) * suave);
      if (t < 1) frame.current = requestAnimationFrame(passo);
    };
    frame.current = requestAnimationFrame(passo);
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
    };
  }, [alvo, duracao]);

  return valor;
}
