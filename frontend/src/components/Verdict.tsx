import { clsx } from "clsx";
import { Level } from "../lib/health";
import { Anomaly, ANOMALY_TYPE_LABELS } from "../types";
import { pluralize } from "../lib/format";
import { TextButton } from "./ui/Button";
import { Explain } from "./ui/Explain";

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

/**
 * A conclusão sobre a máquina, antes de qualquer número.
 *
 * Duas leituras em uma: a frase responde "o que está acontecendo", e a escala
 * de três zonas responde "quão longe do normal isso está" sem exigir que a
 * pessoa interprete uma porcentagem. As zonas são as mesmas três que o sistema
 * usa para classificar toda medida, então não há precisão inventada: a máquina
 * está inteiramente numa delas.
 *
 * Quando está tudo normal a tela não tem cor forte nenhuma — é o que faz um
 * problema saltar sozinho quando aparece.
 */
export function Verdict({
  level,
  openAnomalies,
  learning,
  driver,
  onOpenAnomaly,
  onSeeAll,
}: {
  /** Pior faixa entre os sinais vitais no momento. */
  level: Level;
  /** Anomalias não resolvidas desta máquina, mais recente primeiro. */
  openAnomalies: Anomaly[];
  learning?: { collected: number; needed: number; ml_ready: boolean } | null;
  /** Qual medida está puxando o estado — o "por quê" da frase. */
  driver?: { label: string; value: string } | null;
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

  const activeZone = ZONES.findIndex((z) => z.level === tone);

  return (
    <div className="grid gap-x-10 gap-y-5 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
      <div className="min-w-0">
        <h2
          className={clsx(
            "text-xl font-semibold",
            tone === "crit" ? "text-crit" : tone === "warn" ? "text-warn" : "text-fg"
          )}
        >
          {headline}
        </h2>
        <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-fg-2">{support}</p>

        {(top || driver) && (
          <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5">
            {driver && !openAnomalies.length && (
              <p className="text-xs text-fg-3">
                Puxado por <span className="text-fg-2">{driver.label}</span>{" "}
                <span className="tnum font-mono text-fg-2">{driver.value}</span>
              </p>
            )}
            {top && (
              <>
                <TextButton onClick={() => onOpenAnomaly(top.id)}>Ver o que aconteceu</TextButton>
                {openAnomalies.length > 1 && <TextButton onClick={onSeeAll}>Ver todos</TextButton>}
              </>
            )}
          </div>
        )}
      </div>

      {/*
        Escala de estado: as três zonas sempre visíveis, só a atual acesa.
        Mostrar as outras é o que dá escala à informação — "sob pressão"
        significa pouco sem "problema" desenhado logo adiante.
      */}
      <div
        className="w-full sm:w-56"
        role="img"
        aria-label={`Estado: ${tone === "unknown" ? "sem leituras" : ZONES[activeZone]?.label}`}
      >
        <div className="flex gap-1">
          {ZONES.map((z, i) => (
            <div key={z.level} className="flex-1">
              <div
                className={clsx(
                  "h-1 rounded-full transition-colors duration-500 ease-signal",
                  i === activeZone ? ZONE_FILL[z.level] : "bg-hairline"
                )}
              />
              <p
                className={clsx(
                  "mt-1.5 text-micro transition-colors duration-500",
                  i === activeZone ? clsx("font-medium", ZONE_TEXT[z.level]) : "text-fg-3"
                )}
              >
                {z.label}
              </p>
            </div>
          ))}
        </div>
      </div>

      {learning && !learning.ml_ready && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 sm:col-span-2">
          <div
            className="h-0.5 w-32 overflow-hidden rounded-full bg-sunken"
            role="progressbar"
            aria-label="Progresso do aprendizado"
            aria-valuenow={Math.min(learning.collected, learning.needed)}
            aria-valuemin={0}
            aria-valuemax={learning.needed}
          >
            <div
              className="h-full bg-accent transition-[width] duration-700 ease-signal"
              style={{ width: `${Math.min((learning.collected / learning.needed) * 100, 100)}%` }}
            />
          </div>
          <p className="flex items-center gap-1.5 text-xs text-fg-3">
            Aprendendo o normal deste computador —{" "}
            <span className="tnum font-mono">
              {learning.collected} de {learning.needed}
            </span>{" "}
            leituras
            <Explain term="aprendizado" />
          </p>
        </div>
      )}
    </div>
  );
}
