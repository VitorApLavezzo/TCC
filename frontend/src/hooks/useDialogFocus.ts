import { RefObject, useEffect, useRef } from "react";

// Só o que o Tab alcança: as opções da busca são botões com tabindex=-1
// (navegadas pelas setas) e, contadas aqui, o "último" nunca recebia foco —
// a trava não disparava e o Tab escapava para a página atrás.
const FOCUSABLE = [
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
 */
export function useDialogFocus(
  open: boolean,
  dialogRef: RefObject<HTMLElement>,
  onClose: () => void,
  initialRef?: RefObject<HTMLElement>
) {
  // Em ref, para o efeito não reiniciar a cada render de quem passa uma
  // função nova em `onClose`.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    (initialRef?.current ?? dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE))?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (!focusable || focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
}
