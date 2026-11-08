import { useEffect, useRef, useState } from "react";

/**
 * Número que caminha até o valor novo, em vez de saltar. A duração é fixa,
 * então a velocidade mostra o tamanho do salto antes de a pessoa ler o número.
 * Respeita quem pediu menos movimento no sistema operacional.
 */
export function useCountUp(target: number, durationMs = 420): number {
  const [value, setValue] = useState(target);
  const previous = useRef(target);
  const frame = useRef<number>();

  useEffect(() => {
    const from = previous.current;
    previous.current = target;
    if (from === target) return;

    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    // Salto pequeno não merece animação: mexeria por 400ms para andar 1%.
    if (reduced || Math.abs(target - from) < 1.5) {
      setValue(target);
      return;
    }

    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(from + (target - from) * eased);
      if (t < 1) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
    };
  }, [target, durationMs]);

  return value;
}
