import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
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
  const raw = text ?? (term ? GLOSSARY[term] : undefined);
  const body = raw ? fillPolicy(raw, policy) : undefined;

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

  // Centralizado no "?", o balão de 16rem saía da tela quando o "?" ficava
  // perto da borda (comum no celular). Mede ao abrir e empurra para dentro.
  const bubbleRef = useRef<HTMLSpanElement>(null);
  // Perto do pé da tela (no celular, atrás da barra inferior) abre para cima.
  const [shift, setShift] = useState(0);
  const [up, setUp] = useState(false);
  useLayoutEffect(() => {
    if (!open || !bubbleRef.current) {
      setShift(0);
      setUp(false);
      return;
    }
    const r = bubbleRef.current.getBoundingClientRect();
    const margin = 12;
    if (r.left < margin) setShift(margin - r.left);
    else if (r.right > window.innerWidth - margin) setShift(window.innerWidth - margin - r.right);
    const bottomInset = window.innerWidth < 1024 ? 72 : margin;
    if (r.bottom > window.innerHeight - bottomInset && r.top - r.height - 24 > 0) setUp(true);
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
          ref={bubbleRef}
          id={id}
          role="tooltip"
          style={{ transform: `translateX(calc(-50% + ${shift}px))` }}
          className={`absolute left-1/2 z-40 w-64 ${up ? "bottom-full mb-2" : "top-full mt-2"} max-w-[calc(100vw-1.5rem)] rounded-panel border border-edge bg-surface px-3.5 py-3 text-sm font-normal leading-relaxed text-fg-2 shadow-float`}
        >
          {body}
        </span>
      )}
    </span>
  );
}
