import { clsx } from "clsx";
import { Level, Reading } from "../../lib/health";
import { Explain } from "./Explain";
import { Band, SignalTrace } from "./SignalTrace";

export interface VitalItem {
  label: string;
  /** Já formatado; "--" quando não há leitura. */
  value: string;
  unit?: string;
  reading: Reading;
  /** Segunda linha discreta, ex: "12,4 de 32 GB". */
  detail?: string;
  history?: number[];
  historyMax?: number;
  /** Faixa normal desta medida, desenhada atrás do traço. */
  band?: Band | null;
  /** Cor do trecho fora da faixa, quando a faixa é o normal aprendido. */
  breachTone?: Level;
  /** De onde vem a faixa: "normal daqui às 15h: até 42%". */
  bandLabel?: string;
  term?: string;
  /** Marca a cabeça do traço como leitura corrente. */
  live?: boolean;
  /** Troque a chave a cada leitura nova para disparar o pulso. */
  pulseKey?: number | string;
}

const TONE: Record<string, string> = {
  ok: "text-fg-2",
  warn: "text-warn",
  crit: "text-crit",
  unknown: "text-fg-3",
};

/**
 * Os sinais vitais como canais de um instrumento, não como cartões.
 *
 * Cada canal responde três perguntas na ordem em que elas surgem: quanto está
 * agora (o número), se isso é bom (a palavra de estado) e como chegou até aí
 * (o traço sobre a faixa normal). O número sozinho não diz nada a quem não
 * sabe que 91% de memória é ruim — a faixa desenhada atrás diz.
 *
 * O número fica neutro mesmo em atenção: a cor mora no traço que saiu da faixa
 * e na palavra de estado. Assim uma máquina saudável não tem cor nenhuma.
 */
export function VitalStrip({ items }: { items: VitalItem[] }) {
  return (
    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-panel border border-hairline bg-hairline sm:grid-cols-2 lg:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="min-w-0 bg-surface px-4 pb-3.5 pt-3">
          <div className="flex items-center gap-1.5">
            <span className="channel-label truncate">{item.label}</span>
            {item.term && <Explain term={item.term} />}
          </div>

          <div className="mt-2.5 flex items-baseline justify-between gap-2">
            <p className="tnum font-mono text-readout-sm font-medium text-fg">
              {item.value}
              {item.unit && <span className="ml-0.5 text-md font-normal text-fg-3">{item.unit}</span>}
            </p>
            <span className={clsx("text-xs font-medium", TONE[item.reading.level])}>{item.reading.label}</span>
          </div>

          <div className="mt-3">
            <SignalTrace
              values={item.history ?? []}
              max={item.historyMax}
              band={item.band}
              level={item.reading.level}
              breachTone={item.breachTone}
              height={38}
              live={item.live}
              pulseKey={item.pulseKey}
              label={`${item.label}: ${item.value}${item.unit ?? ""}, ${item.reading.label}${
                item.bandLabel ? `. ${item.bandLabel}` : ""
              }`}
            />
          </div>

          {(item.detail || item.bandLabel) && (
            <p className="tnum mt-2 truncate font-mono text-micro text-fg-3" title={item.bandLabel ?? item.detail}>
              {item.detail ?? item.bandLabel}
            </p>
          )}
          {item.detail && item.bandLabel && (
            <p className="mt-0.5 truncate text-micro text-fg-3" title={item.bandLabel}>
              {item.bandLabel}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

/** Barra de proporção — partição de disco, saúde de bateria. */
export function Meter({
  label,
  percent,
  reading,
  detail,
}: {
  label: string;
  percent: number;
  reading: Reading;
  detail?: string;
}) {
  const tone = reading.level;
  return (
    <div className="flex items-center gap-3 py-1.5">
      <span className="w-24 flex-shrink-0 truncate font-mono text-xs text-fg-2" title={label}>
        {label}
      </span>
      <div
        className="h-1 flex-1 overflow-hidden rounded-full bg-sunken"
        role="progressbar"
        aria-label={label}
        aria-valuenow={Math.round(percent)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={clsx(
            "h-full transition-[width] duration-700 ease-signal",
            tone === "ok" && "bg-fg-3",
            tone === "warn" && "bg-warn",
            tone === "crit" && "bg-crit",
            tone === "unknown" && "bg-hairline"
          )}
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
      </div>
      <span className="tnum w-10 flex-shrink-0 text-right font-mono text-xs text-fg">{percent.toFixed(0)}%</span>
      {detail && (
        <span className="tnum hidden w-24 flex-shrink-0 text-right font-mono text-xs text-fg-3 sm:block">{detail}</span>
      )}
    </div>
  );
}
