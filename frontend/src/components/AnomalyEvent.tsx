import { ReactNode } from "react";
import { clsx } from "clsx";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Anomaly, ANOMALY_TYPE_LABELS } from "../types";
import { Severity } from "./ui/Badge";
import { StatusDot } from "./ui/Layout";
import { processName } from "../lib/format";

/**
 * Um aviso apresentado como evento detectado, não como item de lista.
 *
 * A composição é a de uma fita de registro: o horário à esquerda, uma calha
 * vertical contínua, e um tique na calha exatamente na altura do evento. Lidas
 * em sequência, as linhas viram a linha do tempo das detecções daquela
 * máquina — que é o que elas são de fato. É também o que dá à parte mais
 * importante do produto uma forma própria, em vez de mais uma lista.
 *
 * O tique usa a íris, a mesma cor que marca o instante da detecção nos
 * gráficos e o item ativo na navegação. Detecção tem uma cor só no produto.
 */
export function AnomalyEvent({
  anomaly,
  machineName,
  onOpen,
  action,
  showDate = true,
  className,
}: {
  anomaly: Anomaly;
  /** Só aparece quando a lista mistura máquinas. */
  machineName?: string;
  onOpen: () => void;
  /** Ação à direita, como resolver ou reabrir. */
  action?: ReactNode;
  showDate?: boolean;
  /** Usado pela lista para recolher o item que acabou de ser resolvido. */
  className?: string;
}) {
  const at = new Date(anomaly.detected_at);
  const label = ANOMALY_TYPE_LABELS[anomaly.anomaly_type] || anomaly.anomaly_type;
  const resolved = anomaly.is_resolved;

  return (
    <li className={`flex items-stretch gap-3 overflow-hidden ${className ?? ""}`}>
      {/* Carimbo de tempo: dado medido, então na face da máquina. */}
      <div className="w-11 flex-shrink-0 pt-3 text-right sm:w-12">
        {/* `title` com data e hora completas: o relativo serve para ler rápido,
            e quem vai registrar a ocorrência num chamado precisa do exato. */}
        <p
          className="tnum font-mono text-xs leading-none text-fg-2"
          title={format(at, "EEEE, d 'de' MMMM 'de' yyyy 'às' HH:mm:ss", { locale: ptBR })}
        >
          {format(at, "HH:mm", { locale: ptBR })}
        </p>
        {showDate && (
          <p className="tnum mt-1 font-mono text-micro leading-none text-fg-3">
            {format(at, "dd/MM", { locale: ptBR })}
          </p>
        )}
      </div>

      {/* A calha e o tique da detecção. */}
      <div className="relative flex w-2 flex-shrink-0 justify-center" aria-hidden="true">
        <span className="w-px bg-hairline" />
        <span
          className={clsx(
            "absolute top-[13px] h-[7px] w-[7px] -translate-y-1/2 rotate-45",
            resolved ? "bg-hairline ring-1 ring-edge" : "bg-accent"
          )}
        />
      </div>

      <div className="flex min-w-0 flex-1 items-start gap-3 py-2.5">
        <button
          type="button"
          onClick={onOpen}
          aria-label={`Abrir o aviso ${label}${machineName ? ` de ${machineName}` : ""}`}
          className="-mx-2 min-w-0 flex-1 rounded-control px-2 py-1 text-left transition-colors hover:bg-raised"
        >
          <span className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
            <span className={clsx("text-sm font-medium", resolved ? "text-fg-2" : "text-fg")}>{label}</span>
            {resolved ? (
              <span className="flex items-center gap-1.5 text-xs text-fg-3">
                <StatusDot tone="idle" />
                Resolvida
              </span>
            ) : (
              <Severity severity={anomaly.severity} />
            )}
          </span>

          {anomaly.explanation?.summary && (
            <span className="clamp-2 mt-1 block max-w-prose text-xs leading-relaxed text-fg-2">
              {anomaly.explanation.summary}
            </span>
          )}

          {(machineName ||
            processName(anomaly) ||
            anomaly.during_learning ||
            (anomaly.occurrences ?? 1) > 1 ||
            anomaly.weak_signal) && (
            <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-micro text-fg-3">
              {machineName && <span>{machineName}</span>}
              {processName(anomaly) && <span className="font-mono">{processName(anomaly)}</span>}
              {/* Sem cor de alerta: é uma ressalva sobre o aviso, não um aviso */}
              {anomaly.during_learning && (
                <span className="rounded-full bg-sunken px-2 py-0.5 text-fg-2">
                  durante o aprendizado
                </span>
              )}
              {(anomaly.occurrences ?? 1) > 1 && (
                <span className="rounded-full bg-sunken px-2 py-0.5 text-fg-2">
                  {anomaly.occurrences} vezes
                </span>
              )}
              {anomaly.weak_signal && (
                <span className="rounded-full bg-sunken px-2 py-0.5 text-fg-2">sinal fraco</span>
              )}
            </span>
          )}
        </button>

        {action && <div className="flex-shrink-0 pt-0.5">{action}</div>}
      </div>
    </li>
  );
}

/** A fita em que os eventos são inseridos. */
export function AnomalyTimeline({ children }: { children: ReactNode }) {
  return <ul className="divide-y divide-hairline border-y border-hairline">{children}</ul>;
}
