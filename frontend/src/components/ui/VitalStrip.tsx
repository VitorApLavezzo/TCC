import { clsx } from "clsx";
import { useCountUp } from "../../hooks/useCountUp";
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
  /** Limite de atenção fixo (THRESHOLDS), na escala de `historyMax`. */
  limit?: number;
  /** Limite crítico fixo, na mesma escala. */
  critAt?: number;
}

const TONE: Record<string, string> = {
  ok: "text-fg-2",
  warn: "text-warn",
  crit: "text-crit",
  unknown: "text-fg-3",
};

const SEGS = 20;

/**
 * Medidor segmentado: 20 barras acendem até o valor atual, com uma marca no
 * limite de atenção. Os segmentos abaixo do limite acendem em accent — cor de
 * interação e detecção, não de "saudável" — e só passam a warn/crit quando
 * ultrapassam os limites de THRESHOLDS.
 */
function Segments({ value, max, limit, crit }: { value: number; max: number; limit?: number; crit?: number }) {
  const lit = Math.round((Math.min(Math.max(value, 0), max) / max) * SEGS);
  const limitPct = limit != null ? (limit / max) * 100 : null;
  return (
    <div className="relative pt-1.5" aria-hidden="true">
      <div className="grid h-5 grid-cols-[repeat(20,minmax(0,1fr))] gap-[3px]">
        {Array.from({ length: SEGS }).map((_, i) => {
          const segTopValue = ((i + 1) / SEGS) * max;
          const on = i < lit;
          let cls = "bg-sunken";
          if (on) {
            cls = "bg-accent";
            if (crit != null && segTopValue > crit) cls = "bg-crit";
            else if (limit != null && segTopValue > limit) cls = "bg-warn";
          }
          return <span key={i} className={clsx("rounded-[2px]", cls)} />;
        })}
      </div>
      {limitPct !== null && (
        <span
          className="absolute -top-0.5 h-[26px] w-[2px] -translate-x-1/2 rounded-sm bg-fg-2"
          style={{ left: `${limitPct}%` }}
          title={`limite de atenção: ${limit}`}
        />
      )}
    </div>
  );
}

/**
 * Os sinais vitais como instrumentos de painel, não como cartões de estatística.
 *
 * Cada canal responde três perguntas na ordem em que elas surgem: quanto está
 * agora (o número grande), se isso é bom (a palavra de estado) e como chegou
 * até aí (os segmentos acesos até o limite, e o traço sobre a faixa normal
 * aprendida). Os segmentos acima do limite de atenção acendem em warn/crit —
 * a única cor que comunica "isto é ruim" no instrumento.
 */
export function VitalStrip({ items }: { items: VitalItem[] }) {
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4" aria-label="Sinais vitais">
      {items.map((item) => (
        <Vital key={item.label} item={item} />
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

/**
 * Um sinal vital.
 *
 * Componente próprio por causa do número animado: a transição precisa de
 * estado, e estado não pode nascer dentro do `map`. O valor caminha até o
 * novo em pouco mais de 400 ms, e as barras acompanham o mesmo número — quem
 * olha percebe o tamanho do salto antes de ler o dígito.
 */
function Vital({ item }: { item: VitalItem }) {
    const max = item.historyMax ?? 100;
    const raw = parseFloat(item.value.replace(",", "."));
    const value = Number.isFinite(raw) ? raw : 0;
  const animado = useCountUp(value);
  // Mesma quantidade de casas do texto original, com vírgula: "42,3" continua
  // com uma casa enquanto caminha, senão o número treme de largura.
  const casas = (item.value.split(/[.,]/)[1] ?? "").length;
  const exibido = Number.isFinite(raw)
    ? animado.toFixed(casas).replace(".", ",")
    : item.value;
  return (
      <article
        key={item.label}
        role="meter"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={Number.isFinite(raw) ? raw : undefined}
        aria-label={`${item.label}: ${item.value}${item.unit ?? ""}, ${item.reading.label}${
          item.bandLabel ? `. ${item.bandLabel}` : ""
        }`}
        className="flex min-w-0 flex-col gap-2.5 rounded-panel border border-hairline bg-surface px-4 pb-3.5 pt-3.5"
      >
        <header className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1.5 truncate text-sm font-semibold text-fg">
            {item.label}
            {item.term && <Explain term={item.term} />}
          </span>
          <span className={clsx("flex-shrink-0 text-xs font-semibold", TONE[item.reading.level])}>
            {item.reading.label}
          </span>
        </header>

        <p className="tnum flex items-baseline gap-1 font-mono text-fg">
          <b className="text-[2rem] font-medium leading-none tracking-tight min-[1500px]:text-[2.6rem]">
            {exibido}
          </b>
          {item.unit && <span className="text-base text-fg-3">{item.unit}</span>}
        </p>

        <Segments value={animado} max={max} limit={item.limit} crit={item.critAt} />

        <div className="flex items-center justify-between gap-2 text-xs text-fg-2">
          <span className="tnum truncate font-mono" title={item.detail}>
            {item.detail ?? " "}
          </span>
          {item.limit != null && <span className="flex-shrink-0">limite {item.limit}%</span>}
        </div>

        <SignalTrace
          values={item.history ?? []}
          max={item.historyMax}
          band={item.band}
          level={item.reading.level}
          breachTone={item.breachTone}
          height={34}
          live={item.live}
          pulseKey={item.pulseKey}
          label={`${item.label}: ${item.value}${item.unit ?? ""}, ${item.reading.label}${
            item.bandLabel ? `. ${item.bandLabel}` : ""
          }`}
        />

        {item.bandLabel && (
          <p className="tnum -mt-1 truncate text-micro text-fg-3" title={item.bandLabel}>
            {item.bandLabel}
          </p>
        )}
      </article>
  );
}

