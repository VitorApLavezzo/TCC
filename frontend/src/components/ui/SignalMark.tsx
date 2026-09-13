import { clsx } from "clsx";

/**
 * A marca do AnomalyDetect: quatro barras crescentes, a última em accent.
 *
 * É o produto inteiro em vinte pixels — um sinal ganhando amplitude até o
 * pico, marcado na cor de detecção. As três primeiras herdam a cor do texto
 * ao redor (`currentColor`); a última é sempre accent, o pico do sinal.
 */
export function SignalMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 26 22"
      className={clsx("h-[22px] w-[26px] flex-shrink-0 text-fg", className)}
      fill="none"
      aria-hidden="true"
    >
      <rect x="0" y="14" width="4" height="8" rx="1" fill="currentColor" opacity=".35" />
      <rect x="7" y="9" width="4" height="13" rx="1" fill="currentColor" opacity=".55" />
      <rect x="14" y="4" width="4" height="18" rx="1" fill="currentColor" opacity=".8" />
      <rect x="21" y="0" width="4" height="22" rx="1" fill="rgb(var(--accent))" />
    </svg>
  );
}

/** Assinatura completa: marca mais nome, usada fora da aplicação logada. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={clsx("flex items-center gap-2.5", className)}>
      <SignalMark />
      <span className="text-sm font-semibold tracking-tight text-fg">AnomalyDetect</span>
    </span>
  );
}
