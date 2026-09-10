import { clsx } from "clsx";

/**
 * A marca do AnomalyDetect: uma linha de base com um desvio.
 *
 * É o produto inteiro em vinte pixels — o sinal seguindo normal até sair do
 * padrão. O mesmo desenho que aparece atrás de cada medida do painel, o que
 * faz a marca e a interface falarem a mesma língua.
 */
export function SignalMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 22 12"
      className={clsx("h-3 w-[22px] flex-shrink-0", className)}
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M0 8h5.5l2-5.5 2.2 9L12 8h10"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Assinatura completa: marca mais nome, usada fora da aplicação logada. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={clsx("flex items-center gap-2.5", className)}>
      <SignalMark className="text-accent" />
      <span className="text-sm font-semibold tracking-tight text-fg">AnomalyDetect</span>
    </span>
  );
}
