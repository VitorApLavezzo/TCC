import { ReactNode } from "react";
import { clsx } from "clsx";
import { Check } from "lucide-react";
import { Level } from "../lib/health";
import { Anomaly, ANOMALY_TYPE_LABELS, LearningStatus } from "../types";
import { pluralize } from "../lib/format";
import { TextButton } from "./ui/Button";
import { Explain } from "./ui/Explain";
import { StatusDot } from "./ui/Layout";

/**
 * Um dos dois critérios do aprendizado, cumprido ou pendente.
 *
 * Mesmo vocabulário do passo a passo das anomalias — marcador redondo com
 * borda, contorno em `ok` quando cumprido — para a pessoa reconhecer "isto
 * está feito" no mesmo gesto visual em qualquer tela do painel. Sem risco
 * sobre o texto: estes não são itens que a pessoa faz e risca, são condições
 * que o sistema alcança.
 */
function LearningCriterion({
  done,
  label,
  remaining,
}: {
  done: boolean;
  label: string;
  /** Quanto falta, quando ainda falta. */
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
        {/* Em linha própria: lado a lado, "faltam cerca de 6h" quebrava no
            meio e disputava atenção com o nome do critério. */}
        {!done && remaining && (
          <span className="mt-0.5 block text-micro text-fg-3">{remaining}</span>
        )}
      </span>
    </li>
  );
}

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
            key={tone}
            className={clsx(
              "animate-rise inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-micro font-semibold uppercase tracking-wide",
              CHIP_TONE[tone]
            )}
          >
            <StatusDot tone={tone === "unknown" ? "idle" : tone} />
            {CHIP_LABEL[tone]}
          </span>

          {/*
            `key` na manchete: quando o veredito muda — de "Tudo normal" para
            "Precisa da sua atenção agora" — o React troca o elemento e a
            animação roda. É a informação mais importante da tela, e antes ela
            mudava em silêncio, como se sempre tivesse estado ali.
          */}
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
            <div className="border-t border-hairline pt-3.5 text-xs">
              {/*
                Parágrafo comum, não flex: com `flex flex-wrap` o texto inteiro
                vira um item só e o "?" era empurrado sozinho para a linha de
                baixo. Inline, ele fecha a frase onde deve.
              */}
              <p className="text-fg-2">
                Aprendendo o normal deste computador <Explain term="aprendizado" />
              </p>

              {/*
                Dois critérios que se completam, não um número que sobe. Antes
                dizia "186 de 100 leituras": um contador passando da própria
                meta parece defeito e não respondia a única pergunta que
                importa — o que ainda falta. Sem barra de progresso junto: a
                lista já é o progresso, e a barra ficava um toco de 5% parado
                por horas.
                As duas contas correm juntas e vale a mais lenta: a 5 s por
                leitura, as 100 fecham em 8 minutos.
              */}
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
