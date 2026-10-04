import { useEffect, useId, useRef, useState } from "react";
import { usePolicy } from "../../context/PolicyContext";
import { GLOSSARY } from "../../lib/glossary";
import { fillPolicy } from "../../lib/policy";

/**
 * Ajuda contextual dos termos técnicos.
 *
 * É um "?" tipográfico, não um ícone: numa tela com dez medidas, dez ícones de
 * interrogação viram ruído. Abre no clique — não no hover — para funcionar em
 * toque e por teclado.
 */
export function Explain({ term, text, className }: { term?: string; text?: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const id = useId();
  const policy = usePolicy();
  // Frase que depende de número do servidor some enquanto ele não chega, em
  // vez de mostrar o marcador cru ou um número velho guardado aqui.
  const bruto = text ?? (term ? GLOSSARY[term] : undefined);
  const body = bruto ? fillPolicy(bruto, policy) : undefined;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!body) return null;

  return (
    <span ref={wrapRef} className={`relative inline-flex ${className ?? ""}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="O que isto significa?"
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        className={`flex h-4 w-4 items-center justify-center rounded-full border text-[10px] font-semibold leading-none transition-colors ${
          open ? "border-accent text-accent" : "border-edge text-fg-3 hover:border-fg-3 hover:text-fg-2"
        }`}
      >
        ?
      </button>

      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute left-1/2 top-full z-30 mt-2 w-64 -translate-x-1/2 rounded-panel border border-edge bg-surface px-3.5 py-3 text-sm font-normal leading-relaxed text-fg-2 shadow-float"
        >
          {body}
        </span>
      )}
    </span>
  );
}
