import { ReactNode } from "react";
import { clsx } from "clsx";
import { Check } from "lucide-react";
import { Level } from "../lib/health";
import { Anomaly, ANOMALY_TYPE_LABELS, LearningStatus } from "../types";
import { pluralize } from "../lib/format";
import { stillLearning } from "../lib/learning";
import { verdictTone } from "../lib/verdict";
import { Button, TextButton } from "./ui/Button";
import { Explain } from "./ui/Explain";
import { StatusDot } from "./ui/Layout";

/**
 * Critério do aprendizado, no mesmo marcador do passo a passo das anomalias. Sem risco
 * sobre o texto: são condições que o sistema alcança, não tarefas da pessoa.
 */
function LearningCriterion({
  done,
  label,
  remaining,
}: {
  done: boolean;
  label: string;
  remaining?: string | null;
}) {
  return (
    <li className="flex items-start gap-2">
      <span
        className={clsx(
          "mt-px flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full border",
          done ? "border-ok bg-ok/10" : "border-edge bg-surface"
        )}
        aria-hidden="true"
      >
        {done && <Check className="h-2.5 w-2.5 text-ok" strokeWidth={3} />}
      </span>
      <span className="min-w-0 leading-snug">
        <span className={done ? "text-fg-3" : "text-fg-2"}>{label}</span>
        <span className="sr-only">{done ? " (cumprido)" : ""}</span>
        {/* Em linha própria: lado a lado, "faltam cerca de 6h" quebrava no meio. */}
        {!done && remaining && (
          <span className="mt-0.5 block text-micro text-fg-3">{remaining}</span>
        )}
      </span>
    </li>
  );
}

/** Na ordem em que a máquina caminha entre elas. */
const ZONES: { level: Exclude<Level, "unknown">; label: string }[] = [
  { level: "ok", label: "normal" },
  { level: "warn", label: "atenção" },
  { level: "crit", label: "crítico" },
];

const ZONE_FILL: Record<string, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  crit: "bg-crit",
};

const ZONE_TEXT: Record<string, string> = {
  ok: "text-ok",
  warn: "text-warn",
  crit: "text-crit",
};

const CHIP_TONE: Record<Level, string> = {
  ok: "text-ok bg-ok/[.14]",
  warn: "text-warn bg-warn/[.14]",
  crit: "text-crit bg-crit/[.14]",
  unknown: "text-fg-2 bg-sunken",
};

const CHIP_LABEL: Record<Level, string> = {
  ok: "Normal",
  warn: "Atenção",
  crit: "Crítico",
  unknown: "Sem dados",
};

/**
 * A conclusão sobre a máquina, antes de qualquer número. Tudo normal fica sem cor forte,
 * para que um problema salte sozinho quando aparece.
 */
export function Verdict({
  level,
  openAnomalies,
  learning,
  driver,
  onOpenAnomaly,
  onSeeAll,
  actions,
}: {
  /** Pior faixa entre os sinais vitais no momento. */
  level: Level;
  /** Mais recente primeiro. */
  openAnomalies: Anomaly[];
  learning?: LearningStatus | null;
  /** Qual medida está puxando o estado — o "por quê" da frase. */
  driver?: { label: string; value: string } | null;
  onOpenAnomaly: (id: number) => void;
  onSeeAll: () => void;
  actions?: ReactNode;
}) {
  const top = openAnomalies[0];
  const critical = openAnomalies.some((a) => a.severity === "critical");
  const high = openAnomalies.some((a) => a.severity === "high");

  const tone = verdictTone(level, openAnomalies);

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

  const activeZone = ZONES.findIndex((z) => z.level === tone);

  return (
    <div className="rounded-panel border border-edge bg-raised p-6 sm:p-7">
      <div className="grid gap-x-10 gap-y-6 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
        <div className="min-w-0">
          <span
            key={tone}
            className={clsx(
              "animate-rise inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-micro font-semibold uppercase tracking-wide",
              CHIP_TONE[tone]
            )}
          >
            <StatusDot tone={tone === "unknown" ? "idle" : tone} />
            {CHIP_LABEL[tone]}
          </span>

          {/* `key` na manchete: quando o veredito muda, o React troca o elemento e a animação roda. */}
          <h2
            key={headline}
            className="animate-rise mt-3 font-display text-[1.9rem] font-bold leading-[1.1] tracking-tight text-fg sm:text-[2.1rem]"
          >
            {headline}
          </h2>
          <p className="mt-1.5 max-w-[60ch] text-sm leading-relaxed text-fg-2">
            {support}
            {driver && !openAnomalies.length && (
              <>
                {" "}
                <span className="text-fg-2">
                  Puxado por <span className="text-fg">{driver.label}</span>{" "}
                  <span className="tnum font-mono text-fg">{driver.value}</span>.
                </span>
              </>
            )}
          </p>

          {/* Com aviso em aberto, a ação principal é abrir o aviso; o resto é secundário. */}
          {(top || actions) && (
            <div className="mt-[18px] flex flex-wrap items-center gap-2.5">
              {top && (
                <Button variant="primary" onClick={() => onOpenAnomaly(top.id)}>
                  Ver o que aconteceu
                </Button>
              )}
              {actions}
              {openAnomalies.length > 1 && (
                <TextButton onClick={onSeeAll} className="ml-1">
                  Ver os {openAnomalies.length} avisos
                </TextButton>
              )}
            </div>
          )}
        </div>

        <div className="flex w-full flex-col gap-3.5 sm:w-60">
          <div role="img" aria-label={`Estado: ${tone === "unknown" ? "sem leituras" : ZONES[activeZone]?.label}`}>
            <div className="grid grid-cols-3 gap-1">
              {ZONES.map((z, i) => (
                <div key={z.level} className="flex flex-col gap-1.5">
                  <div
                    className={clsx(
                      "h-1.5 rounded-full transition-colors duration-500 ease-signal",
                      i === activeZone ? ZONE_FILL[z.level] : "bg-sunken"
                    )}
                  />
                  <p
                    className={clsx(
                      "text-micro transition-colors duration-500",
                      i === activeZone ? clsx("font-semibold", ZONE_TEXT[z.level]) : "text-fg-3"
                    )}
                  >
                    {z.label}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {learning && stillLearning(learning) && (
            <div className="border-t border-hairline pt-3.5 text-xs">
              {/* Parágrafo comum, não flex: com `flex-wrap` o "?" ia sozinho para a linha de baixo. */}
              <p className="text-fg-2">
                Aprendendo o normal deste computador <Explain term="aprendizado" />
              </p>

              {/* Dois critérios que correm juntos e vale o mais lento: a 5 s por leitura, as
                  100 fecham em 8 minutos. Um contador passaria da própria meta. */}
              <ul className="mt-2.5 space-y-2">
                <LearningCriterion
                  done={!!learning.samples_done}
                  label={`${learning.needed} leituras`}
                  remaining={
                    learning.remaining_samples ? `faltam ${learning.remaining_samples}` : null
                  }
                />
                <LearningCriterion
                  done={!!learning.hours_done}
                  label={`${learning.hours_needed} horas acompanhando`}
                  remaining={
                    learning.remaining_hours_label
                      ? `faltam cerca de ${learning.remaining_hours_label}`
                      : null
                  }
                />
              </ul>

              <p className="mt-3 leading-relaxed text-fg-3">
                Até lá, o que for encontrado fica registrado aqui sem virar aviso.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
