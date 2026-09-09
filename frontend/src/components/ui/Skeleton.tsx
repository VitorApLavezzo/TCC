import { clsx } from "clsx";

/**
 * Placeholder de carregamento. Antes a tela ficava em branco e depois surgia
 * inteira — indistinguível de "esta máquina não tem dados".
 */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={clsx("animate-pulse rounded bg-sunken", className)} />;
}

/** Esqueleto da faixa de sinais vitais, com a mesma malha do componente real. */
export function VitalsSkeleton() {
  return (
    <div
      role="status"
      aria-label="Carregando as leituras"
      className="grid grid-cols-2 divide-hairline rounded-panel border border-hairline bg-surface sm:divide-x lg:grid-cols-4"
    >
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className={clsx("px-5 py-4", i < 2 && "border-b border-hairline lg:border-b-0")}>
          <Skeleton className="h-3 w-16" />
          <Skeleton className="mt-2.5 h-6 w-14" />
          <Skeleton className="mt-3 h-5 w-full" />
          <Skeleton className="mt-2.5 h-3 w-12" />
        </div>
      ))}
    </div>
  );
}

/** Esqueleto de lista com a mesma altura de linha da lista real. */
export function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Carregando a lista" className="divide-y divide-hairline">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="py-3.5">
          <Skeleton className="h-3.5 w-56" />
          <Skeleton className="mt-2 h-3 w-full max-w-md" />
          <Skeleton className="mt-2 h-2.5 w-40" />
        </div>
      ))}
    </div>
  );
}
