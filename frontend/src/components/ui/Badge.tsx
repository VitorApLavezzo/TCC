import { clsx } from "clsx";
import { SEVERITY_LABELS } from "../../types";
import { StatusDot } from "./Layout";

/**
 * Cor de cada gravidade em quatro degraus (cinza, amarelo, vermelho tênue,
 * vermelho cheio), para a urgência se ver sem ler a palavra.
 */
const TONE: Record<string, "ok" | "warn" | "crit" | "idle"> = {
  low: "idle",
  medium: "warn",
  high: "crit",
  critical: "crit",
};

/** Cor do ponto de uma gravidade, para listas que mostram só o ponto. */
export function severityTone(severity?: string | null): "warn" | "crit" | "idle" {
  const tone = TONE[severity ?? ""] ?? "idle";
  return tone === "ok" ? "idle" : tone;
}

const CHIP_TONE: Record<"ok" | "warn" | "crit" | "idle", string> = {
  ok: "text-ok bg-ok/[.14]",
  warn: "text-warn bg-warn/[.14]",
  crit: "text-crit bg-crit/[.14]",
  idle: "text-fg-2 bg-sunken",
};

/**
 * Gravidade como chip: ponto + palavra dentro de uma pílula com fundo tênue
 * na cor do estado. O ponto e o fundo carregam a cor; o texto carrega o
 * significado — nunca só a cor sozinha. Crítica é a única pílula cheia.
 */
export function Severity({ severity, className }: { severity: string; className?: string }) {
  const tone = TONE[severity] ?? "idle";
  const solid = severity === "critical";
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-micro font-semibold uppercase tracking-wide",
        solid ? "bg-crit text-inverse-fg" : CHIP_TONE[tone],
        className
      )}
    >
      {solid ? (
        <span className="inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full bg-current" aria-hidden="true" />
      ) : (
        <StatusDot tone={tone} />
      )}
      {SEVERITY_LABELS[severity] || severity}
    </span>
  );
}
