import { useEffect, useRef, useState } from "react";
import { actionsApi, errorMessage } from "../services/api";
import { Machine } from "../types";
import { useToast } from "./ui/Toast";
import { Gamepad2 } from "lucide-react";

/**
 * "Estou fazendo algo pesado."
 *
 * Enquanto ativo, os avisos de desempenho ficam suspensos e as leituras não
 * entram no aprendizado — jogar ou renderizar não vira anomalia nem contamina
 * o normal aprendido. Avisos de segurança continuam valendo.
 */
export function FocusModeControl({ machine, onChange }: { machine: Machine; onChange?: () => void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const active = machine.focus_mode_until && new Date(machine.focus_mode_until) > new Date();
  const wrapRef = useRef<HTMLDivElement>(null);

  // Fecha com Esc ou clicando fora, como qualquer menu.
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

  const set = async (minutes: number) => {
    setBusy(true);
    try {
      await actionsApi.focusMode(machine.id, minutes);
      toast.success(minutes === 0 ? "Modo desligado." : `Ativado por ${minutes >= 60 ? `${minutes / 60} h` : `${minutes} min`}.`);
      setOpen(false);
      onChange?.();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (active) {
    return (
      <button
        type="button"
        onClick={() => set(0)}
        disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-control border border-accent/40 bg-accent/[.08] px-2.5 py-1 text-xs text-accent transition-colors hover:bg-accent/[.12]"
      >
        <Gamepad2 size={12} aria-hidden="true" />
        Modo atividade pesada ativo — desligar
      </button>
    );
  }

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
        className="inline-flex items-center gap-1.5 rounded-control border border-edge px-2.5 py-1 text-xs text-fg-2 transition-colors hover:bg-raised hover:text-fg"
      >
        <Gamepad2 size={12} aria-hidden="true" />
        Vou fazer algo pesado
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1.5 w-52 rounded-panel border border-edge bg-surface p-1.5 shadow-float">
          <p className="px-2 py-1.5 text-micro leading-relaxed text-fg-3">
            Suspende avisos de desempenho e tira estas horas do aprendizado.
          </p>
          {[
            { label: "Por 1 hora", m: 60 },
            { label: "Por 3 horas", m: 180 },
            { label: "Por 6 horas", m: 360 },
          ].map((o) => (
            <button
              key={o.m}
              type="button"
              onClick={() => set(o.m)}
              disabled={busy}
              className="block w-full rounded-control px-2 py-1.5 text-left text-sm text-fg-2 transition-colors hover:bg-raised hover:text-fg"
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
