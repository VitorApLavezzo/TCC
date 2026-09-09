import { ReactNode } from "react";

/**
 * Tela vazia como convite à ação.
 *
 * Alinhada à esquerda e sem ilustração: o ícone dentro de um círculo cinza
 * centralizado é o clichê de empty state e não acrescenta informação. O que a
 * pessoa precisa é do próximo passo.
 */
export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  action?: ReactNode;
}) {
  return (
    <div className="rounded-panel border border-dashed border-edge px-5 py-8">
      <p className="text-base font-medium text-fg">{title}</p>
      <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-fg-2">{body}</p>
      {action && <div className="mt-4 flex flex-wrap gap-2">{action}</div>}
    </div>
  );
}
