import { clsx } from "clsx";

/** Placeholder de carregamento, para não parecer "esta máquina não tem dados". */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={clsx("animate-pulse rounded bg-sunken", className)} />;
}

/** Esqueleto dos canais, com a mesma malha e as mesmas alturas do real. */
export function VitalsSkeleton() {
  return (
    <div
      role="status"
      aria-label="Carregando as leituras"
      className="grid grid-cols-1 gap-px overflow-hidden rounded-panel border border-hairline bg-hairline sm:grid-cols-2 lg:grid-cols-4"
    >
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="bg-surface px-4 pb-3.5 pt-3">
          <Skeleton className="h-2.5 w-20" />
          <Skeleton className="mt-3 h-6 w-16" />
          <Skeleton className="mt-3.5 h-[38px] w-full" />
          <Skeleton className="mt-2 h-2.5 w-16" />
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
