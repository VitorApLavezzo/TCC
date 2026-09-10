import { createContext, useCallback, useContext, useMemo, useRef, useState, ReactNode } from "react";
import { X } from "lucide-react";
import { clsx } from "clsx";
import { StatusDot } from "./Layout";

type Kind = "success" | "error" | "info";

interface Toast {
  id: number;
  kind: Kind;
  message: string;
  /** O que a pessoa pode fazer a respeito. Erros sempre trazem um. */
  hint?: string;
}

interface Ctx {
  toast: (kind: Kind, message: string, hint?: string) => void;
  success: (message: string, hint?: string) => void;
  error: (message: string, hint?: string) => void;
  info: (message: string, hint?: string) => void;
}

const ToastCtx = createContext<Ctx | null>(null);

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error("useToast precisa estar dentro de <ToastProvider>");
  return ctx;
}

const DOT: Record<Kind, "ok" | "crit" | "idle"> = {
  success: "ok",
  error: "crit",
  info: "idle",
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const toast = useCallback(
    (kind: Kind, message: string, hint?: string) => {
      const id = ++seq.current;
      setItems((prev) => [...prev.slice(-2), { id, kind, message, hint }]);
      // Erros ficam mais tempo: costumam pedir leitura, não só ciência.
      setTimeout(() => dismiss(id), kind === "error" ? 9000 : 5000);
    },
    [dismiss]
  );

  const api = useMemo<Ctx>(
    () => ({
      toast,
      success: (m, h) => toast("success", m, h),
      error: (m, h) => toast("error", m, h),
      info: (m, h) => toast("info", m, h),
    }),
    [toast]
  );

  return (
    <ToastCtx.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(21rem,calc(100vw-2rem))] flex-col gap-2"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className={clsx(
              "pointer-events-auto flex animate-rise items-start gap-2.5 rounded-panel border border-edge bg-surface px-3.5 py-3 shadow-float"
            )}
          >
            <StatusDot tone={DOT[t.kind]} className="mt-1.5" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-fg">{t.message}</p>
              {t.hint && <p className="mt-1 text-xs leading-relaxed text-fg-2">{t.hint}</p>}
            </div>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              aria-label="Fechar aviso"
              className="-mr-1 -mt-1 flex-shrink-0 rounded p-1 text-fg-3 hover:text-fg"
            >
              <X size={13} aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
