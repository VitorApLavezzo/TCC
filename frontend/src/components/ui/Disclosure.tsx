import { ReactNode } from "react";
import { clsx } from "clsx";
import { ChevronDown } from "lucide-react";

/**
 * Conteúdo de segundo nível, fechado por padrão.
 *
 * Usa `<details>` nativo: já vem focável, operável por teclado e anunciado
 * como expansível pelo leitor de tela, sem estado em React nem ARIA à mão.
 *
 * O uso aqui não é economizar espaço — é ordenar. Numa tela onde a IA escreve
 * três mil caracteres, mostrar tudo de uma vez faz a pessoa não ler nada. O
 * que responde "o que eu faço agora" fica aberto; o aprofundamento fica a um
 * clique, com o rótulo dizendo o que há dentro para a escolha ser informada.
 */
export function Disclosure({
  title,
  note,
  children,
  defaultOpen,
  className,
}: {
  title: string;
  /** Pista do conteúdo, para decidir se vale abrir. */
  note?: string;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  return (
    <details open={defaultOpen} className={clsx("group border-t border-hairline", className)}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-control py-3 transition-colors hover:text-fg [&::-webkit-details-marker]:hidden">
        <span className="text-sm font-medium text-fg">{title}</span>
        <span className="flex flex-shrink-0 items-center gap-2.5">
          {note && <span className="text-xs text-fg-3">{note}</span>}
          <ChevronDown
            size={14}
            aria-hidden="true"
            className="text-fg-3 transition-transform duration-200 ease-signal group-open:rotate-180"
          />
        </span>
      </summary>
      <div className="pb-5 pt-0.5">{children}</div>
    </details>
  );
}
