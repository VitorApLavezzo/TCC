import { ReactNode } from "react";
import { clsx } from "clsx";
import { Level } from "../lib/health";
import { Anomaly, ANOMALY_TYPE_LABELS, LearningStatus } from "../types";
import { pluralize } from "../lib/format";
import { TextButton } from "./ui/Button";
import { Explain } from "./ui/Explain";
import { StatusDot } from "./ui/Layout";

/** As três zonas do estado, na ordem em que a máquina caminha entre elas. */
const ZONES: { level: Exclude<Level, "unknown">; label: string }[] = [
  { level: "ok", label: "normal" },
  { level: "warn", label: "sob pressão" },
  { level: "crit", label: "problema" },
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
 * A conclusão sobre a máquina, antes de qualquer número.
 *
 * É o único bloco elevado da tela: um chip de estado, a manchete grande e a
 * frase do motivo respondem "o que está acontecendo"; a escala de três zonas
 * e o progresso do aprendizado, à direita, respondem "quão longe do normal
 * isso está" e "quanto o sistema já conhece desta máquina". As zonas são as
 * mesmas três que classificam toda medida do painel — nenhuma precisão
 * inventada.
 *
 * Quando está tudo normal o chip e a manchete não têm cor forte nenhuma — é o
 * que faz um problema saltar sozinho quando aparece.
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
  /** Anomalias não resolvidas desta máquina, mais recente primeiro. */
  openAnomalies: Anomaly[];
  learning?: LearningStatus | null;
  /** Qual medida está puxando o estado — o "por quê" da frase. */
  driver?: { label: string; value: string } | null;
  onOpenAnomaly: (id: number) => void;
  onSeeAll: () => void;
  /** Ações da máquina: diagnóstico e ver análises. */
  actions?: ReactNode;
}) {
  const top = openAnomalies[0];
  // Vale a régua mais lenta: leituras suficientes E tempo de relógio suficiente
  const learningProgress = Math.min(
    (learning?.collected ?? 0) / (learning?.needed || 1),
    learning?.hours_needed ? (learning.hours ?? 0) / learning.hours_needed : 1,
    1,
  );
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

  const activeZone = ZONES.findIndex((z) => z.level === tone);

  return (
    <div className="rounded-panel border border-edge bg-raised p-6 sm:p-7">
      <div className="grid gap-x-10 gap-y-6 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
        <div className="min-w-0">
          <span
            className={clsx(
              "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-micro font-semibold uppercase tracking-wide",
              CHIP_TONE[tone]
            )}
          >
            <StatusDot tone={tone === "unknown" ? "idle" : tone} />
            {CHIP_LABEL[tone]}
          </span>

          <h2 className="mt-3 font-display text-[1.9rem] font-bold leading-[1.1] tracking-tight text-fg sm:text-[2.1rem]">
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

          {top && (
            <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1.5">
              <TextButton onClick={() => onOpenAnomaly(top.id)}>Ver o que aconteceu</TextButton>
              {openAnomalies.length > 1 && <TextButton onClick={onSeeAll}>Ver todos</TextButton>}
            </div>
          )}

          {actions && <div className="mt-[18px] flex flex-wrap gap-2.5">{actions}</div>}
        </div>

        {/*
          Escala de estado (as três zonas sempre visíveis, só a atual acesa) e,
          logo abaixo, o progresso do aprendizado — as duas respostas de
          "quão longe" ficam juntas, à direita da manchete.
        */}
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

          {learning && (learning.learning ?? !learning.ml_ready) && (
            <div className="text-xs text-fg-2">
              <p className="flex flex-wrap items-center gap-1.5">
                Aprendendo o normal deste computador:{" "}
                <span className="tnum font-mono text-fg">
                  {learning.collected} de {learning.needed}
                </span>{" "}
                leituras
                {learning.hours_needed != null && (
                  <>
                    ·{" "}
                    <span className="tnum font-mono text-fg">
                      {Math.floor(learning.hours ?? 0)}h de {learning.hours_needed}h
                    </span>
                  </>
                )}
                <Explain term="aprendizado" />
              </p>
              {/* As duas contas correm juntas e vale a mais lenta: 100 leituras
                  a cada 10 s seriam 17 min, que não são o normal de ninguém. */}
              <div
                className="mt-1.5 h-1 overflow-hidden rounded-full bg-sunken"
                role="progressbar"
                aria-label="Progresso do aprendizado"
                aria-valuenow={Math.round(learningProgress * 100)}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div
                  className="h-full min-w-[6px] rounded-full bg-accent transition-[width] duration-700 ease-signal"
                  style={{ width: `${learningProgress * 100}%` }}
                />
              </div>
              <p className="mt-1.5 text-fg-3">
                Até lá, tudo que for encontrado fica registrado aqui sem virar aviso — só
                sinais que não dependem de histórico, como um programa disfarçado ou um
                arquivo-isca mexido, interrompem você.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
