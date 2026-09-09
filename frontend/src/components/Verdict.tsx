import { clsx } from "clsx";
import { Level } from "../lib/health";
import { Anomaly, ANOMALY_TYPE_LABELS } from "../types";
import { pluralize } from "../lib/format";
import { StatusDot } from "./ui/Layout";
import { TextButton } from "./ui/Button";
import { Explain } from "./ui/Explain";

/**
 * A conclusão, em uma frase, antes de qualquer número.
 *
 * Deixou de ser um painel colorido de destaque: agora é uma linha de texto com
 * um ponto de status. Quando está tudo bem, a tela não tem cor nenhuma — e é
 * justamente isso que faz um problema saltar quando aparece.
 */
export function Verdict({
  level,
  openAnomalies,
  learning,
  onOpenAnomaly,
  onSeeAll,
}: {
  /** Pior faixa entre os sinais vitais no momento. */
  level: Level;
  /** Anomalias não resolvidas desta máquina, mais recente primeiro. */
  openAnomalies: Anomaly[];
  learning?: { collected: number; needed: number; ml_ready: boolean } | null;
  onOpenAnomaly: (id: number) => void;
  onSeeAll: () => void;
}) {
  const top = openAnomalies[0];
  const critical = openAnomalies.some((a) => a.severity === "critical");
  const high = openAnomalies.some((a) => a.severity === "high");

  const tone: Level = critical ? "crit" : high || openAnomalies.length ? "warn" : level;

  const headline = critical
    ? "Precisa da sua atenção agora"
    : high
      ? "Precisa de atenção hoje"
      : openAnomalies.length
        ? "Há algo para olhar quando puder"
        : tone === "crit"
          ? "No limite da capacidade"
          : tone === "warn"
            ? "Sob pressão"
            : tone === "unknown"
              ? "Sem leituras ainda"
              : "Tudo normal";

  const support = openAnomalies.length
    ? `${pluralize(openAnomalies.length, "aviso em aberto", "avisos em aberto")}${
        top ? ` · ${(ANOMALY_TYPE_LABELS[top.anomaly_type] || top.anomaly_type).toLowerCase()}` : ""
      }`
    : tone === "crit"
      ? "Um sinal vital passou do limite seguro."
      : tone === "warn"
        ? "Um sinal vital está alto, mas nada foi classificado como problema."
        : tone === "unknown"
          ? "A primeira leitura aparece assim que o agente enviar."
          : "Nenhum aviso em aberto neste computador.";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="flex items-baseline gap-2">
          <StatusDot tone={tone === "unknown" ? "idle" : tone} className="translate-y-[-2px]" />
          <span
            className={clsx(
              "text-lg font-semibold tracking-tight",
              tone === "crit" ? "text-crit" : tone === "warn" ? "text-warn" : "text-fg"
            )}
          >
            {headline}
          </span>
        </span>
        <span className="text-sm text-fg-2">{support}</span>
        {top && (
          <span className="flex items-center gap-3">
            <TextButton onClick={() => onOpenAnomaly(top.id)}>Ver o que aconteceu</TextButton>
            {openAnomalies.length > 1 && <TextButton onClick={onSeeAll}>Ver todos</TextButton>}
          </span>
        )}
      </div>

      {learning && !learning.ml_ready && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <div
            className="h-0.5 w-32 overflow-hidden rounded-full bg-sunken"
            role="progressbar"
            aria-label="Progresso do aprendizado"
            aria-valuenow={Math.min(learning.collected, learning.needed)}
            aria-valuemin={0}
            aria-valuemax={learning.needed}
          >
            <div
              className="h-full bg-fg-3"
              style={{ width: `${Math.min((learning.collected / learning.needed) * 100, 100)}%` }}
            />
          </div>
          <p className="tnum flex items-center gap-1.5 text-xs text-fg-3">
            Aprendendo o normal deste computador — {learning.collected} de {learning.needed} leituras
            <Explain term="aprendizado" />
          </p>
        </div>
      )}
    </div>
  );
}
