import { createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode } from "react";
import { Button } from "./Button";

interface Request {
  title: string;
  /** O que exatamente vai acontecer, incluindo o nome do alvo. */
  body: ReactNode;
  confirmLabel: string;
  destructive?: boolean;
}

type Resolver = (ok: boolean) => void;

const ConfirmCtx = createContext<((req: Request) => Promise<boolean>) | null>(null);

export function useConfirm() {
  const ctx = useContext(ConfirmCtx);
  if (!ctx) throw new Error("useConfirm precisa estar dentro de <ConfirmProvider>");
  return ctx;
}

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [request, setRequest] = useState<Request | null>(null);
  const resolverRef = useRef<Resolver | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const confirm = useCallback((req: Request) => {
    setRequest(req);
    return new Promise<boolean>((resolve) => {
      resolverRef.current = resolve;
    });
  }, []);

  const settle = useCallback((ok: boolean) => {
    resolverRef.current?.(ok);
    resolverRef.current = null;
    setRequest(null);
  }, []);

  // Foco inicial no "Cancelar" e Esc cancela: numa ação destrutiva o caminho
  // seguro precisa ser o padrão. O Tab fica preso dentro do diálogo e o foco
  // volta para o botão que o abriu quando ele fecha — sem isso, quem navega
  // por teclado sai para a página atrás, que está inerte, e se perde.
  useEffect(() => {
    if (!request) return;
    const anterior = document.activeElement as HTMLElement | null;
    cancelRef.current?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        settle(false);
        return;
      }
      if (e.key !== "Tab") return;
      const foco = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
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
  }, [request, settle]);

  return (
    <ConfirmCtx.Provider value={confirm}>
      {children}
      {request && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
          onMouseDown={(e) => e.target === e.currentTarget && settle(false)}
        >
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            className="w-full max-w-md rounded-panel border border-edge bg-surface shadow-float"
          >
            <div className="px-5 py-4">
              <h2 id="confirm-title" className="text-base font-semibold text-fg">
                {request.title}
              </h2>
              <div className="mt-2 text-sm leading-relaxed text-fg-2">{request.body}</div>
            </div>
            <div className="flex justify-end gap-2 border-t border-hairline px-5 py-3">
              <Button ref={cancelRef} variant="secondary" onClick={() => settle(false)}>
                Cancelar
              </Button>
              <Button
                variant={request.destructive ? "danger" : "primary"}
                onClick={() => settle(true)}
              >
                {request.confirmLabel}
              </Button>
            </div>
          </div>
        </div>
      )}
    </ConfirmCtx.Provider>
  );
}
