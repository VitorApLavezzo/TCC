import { useRef } from "react";
import { useDialogFocus } from "../../hooks/useDialogFocus";

const ATALHOS: [string, string][] = [
  ["Ctrl K  ou  /", "Buscar computador, aviso ou tela"],
  ["g depois p", "Ir para o painel"],
  ["g depois c", "Ir para os computadores"],
  ["g depois a", "Ir para os avisos"],
  ["g depois q", "Perguntar ao seu computador"],
  ["?", "Mostrar esta lista"],
  ["Esc", "Fechar o que estiver aberto"],
];

/** A lista de atalhos, aberta com "?" — o mesmo gesto de quase todo produto. */
export function ShortcutsSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useDialogFocus(open, dialogRef, onClose);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Atalhos de teclado"
           className="w-full max-w-sm rounded-panel border border-edge bg-surface p-5 shadow-float">
        <h2 className="font-display text-base font-semibold text-fg">Atalhos de teclado</h2>
        <dl className="mt-3 divide-y divide-hairline">
          {ATALHOS.map(([tecla, oque]) => (
            <div key={tecla} className="flex items-baseline justify-between gap-4 py-2">
              <dt className="text-sm text-fg-2">{oque}</dt>
              <dd>
                <kbd className="rounded border border-edge px-1.5 py-0.5 font-mono text-micro text-fg-3">{tecla}</kbd>
              </dd>
            </div>
          ))}
        </dl>
        <button
          type="button"
          onClick={onClose}
          className="mt-4 w-full rounded-control border border-edge py-2 text-sm text-fg-2 hover:bg-raised hover:text-fg"
        >
          Fechar
        </button>
      </div>
    </div>
  );
}
