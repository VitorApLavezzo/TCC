import { clsx } from "clsx";
import { SEVERITY_LABELS } from "../../types";
import { StatusDot } from "./Layout";

const TONE: Record<string, "ok" | "warn" | "crit" | "idle"> = {
  low: "idle",
  medium: "warn",
  high: "warn",
  critical: "crit",
};

/**
 * Severidade como ponto + palavra, não como pílula colorida.
 *
 * Numa lista de vinte avisos, vinte pílulas com fundo competem entre si e com
 * o próprio título. O ponto carrega a cor; o texto carrega o significado.
 */
export function Severity({ severity, className }: { severity: string; className?: string }) {
  const tone = TONE[severity] ?? "idle";
  return (
    <span className={clsx("inline-flex items-center gap-1.5", className)}>
      <StatusDot tone={tone} />
      <span
        className={clsx(
          "text-xs",
          tone === "crit" && "font-medium text-crit",
          tone === "warn" && "text-warn",
          tone === "idle" && "text-fg-3"
        )}
      >
        {SEVERITY_LABELS[severity] || severity}
      </span>
    </span>
  );
}
