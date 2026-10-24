import { RefObject, useEffect, useRef } from "react";

// Só o que o Tab alcança: as opções da busca são botões com tabindex=-1
// (navegadas pelas setas) e, contadas aqui, o "último" nunca recebia foco —
// a trava não disparava e o Tab escapava para a página atrás.
const FOCAVEIS = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]",
]
  .map((s) => `${s}:not([tabindex="-1"])`)
  .join(", ");

/**
 * Foco de uma janela sobreposta: entra no elemento inicial, fica preso no
 * Tab, Esc fecha de qualquer ponto e, ao fechar, volta para quem abriu.
 *
 * Era o que só o diálogo de confirmação fazia. A busca (Ctrl+K) e a lista de
 * atalhos deixavam o Tab escapar para a página atrás — inerte sob o fundo
 * escuro — e o foco se perdia ao fechar.
 */
export function useDialogFocus(
  open: boolean,
  dialogRef: RefObject<HTMLElement>,
  onClose: () => void,
  initialRef?: RefObject<HTMLElement>
) {
  // Em ref, para o efeito não reiniciar a cada render de quem passa uma
  // função nova em `onClose`.
  const fechar = useRef(onClose);
  fechar.current = onClose;

  useEffect(() => {
    if (!open) return;
    const anterior = document.activeElement as HTMLElement | null;
    (initialRef?.current ?? dialogRef.current?.querySelector<HTMLElement>(FOCAVEIS))?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        fechar.current();
        return;
      }
      if (e.key !== "Tab") return;
      const foco = dialogRef.current?.querySelectorAll<HTMLElement>(FOCAVEIS);
      if (!foco || foco.length === 0) return;
      const primeiro = foco[0];
      const ultimo = foco[foco.length - 1];
      if (e.shiftKey && document.activeElement === primeiro) {
        e.preventDefault();
        ultimo.focus();
      } else if (!e.shiftKey && document.activeElement === ultimo) {
        e.preventDefault();
        primeiro.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      anterior?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
}
