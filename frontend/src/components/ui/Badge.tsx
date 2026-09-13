import { clsx } from "clsx";
import { SEVERITY_LABELS } from "../../types";
import { StatusDot } from "./Layout";

const TONE: Record<string, "ok" | "warn" | "crit" | "idle"> = {
  low: "idle",
  medium: "warn",
  high: "warn",
  critical: "crit",
};

const CHIP_TONE: Record<"ok" | "warn" | "crit" | "idle", string> = {
  ok: "text-ok bg-ok/[.14]",
  warn: "text-warn bg-warn/[.14]",
  crit: "text-crit bg-crit/[.14]",
  idle: "text-fg-2 bg-sunken",
};

/**
 * Severidade como chip: ponto + palavra dentro de uma pílula com fundo tênue
 * na cor do estado. O ponto e o fundo carregam a cor; o texto carrega o
 * significado — nunca só a cor sozinha.
 */
export function Severity({ severity, className }: { severity: string; className?: string }) {
  const tone = TONE[severity] ?? "idle";
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-micro font-semibold uppercase tracking-wide",
        CHIP_TONE[tone],
        className
      )}
    >
      <StatusDot tone={tone} />
      {SEVERITY_LABELS[severity] || severity}
    </span>
  );
}
