import { clsx } from "clsx";
import { Reading } from "../../lib/health";
import { Explain } from "./Explain";
import { Sparkline } from "./Sparkline";

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
  term?: string;
}

const TONE: Record<string, string> = {
  ok: "text-ok",
  warn: "text-warn",
  crit: "text-crit",
  unknown: "text-fg-3",
};

/**
 * Painel de instrumentos: uma faixa com divisórias internas.
 *
 * A versão anterior fazia quatro cartões separados, cada um com borda, fundo
 * e sombra própria — quatro objetos disputando atenção para mostrar quatro
 * números do mesmo assunto. Aqui é um objeto só.
 *
 * O número fica neutro; a cor aparece no rótulo de faixa embaixo. Assim uma
 * tela saudável não tem nenhuma cor forte, e um problema salta sozinho.
 */
export function VitalStrip({ items }: { items: VitalItem[] }) {
  return (
    <div className="grid grid-cols-2 divide-hairline rounded-panel border border-hairline bg-surface sm:divide-x lg:grid-cols-4">
      {items.map((item, i) => (
        <div
          key={item.label}
          className={clsx(
            "min-w-0 px-5 py-4",
            // Divisórias horizontais só existem na quebra de duas colunas.
            i < items.length - 2 && "border-b border-hairline lg:border-b-0",
            i % 2 === 1 && "border-l border-hairline sm:border-l-0"
          )}
        >
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm text-fg-2">{item.label}</span>
            {item.term && <Explain term={item.term} />}
          </div>

          <p className="tnum mt-2 text-2xl font-medium text-fg">
            {item.value}
            {item.unit && <span className="ml-1 text-base font-normal text-fg-2">{item.unit}</span>}
          </p>

          {item.history && item.history.length > 1 && (
            <div className="mt-2.5 text-fg-3">
              <Sparkline values={item.history} max={item.historyMax} />
            </div>
          )}

          <div className="mt-2.5 flex items-baseline justify-between gap-2">
            <span className={clsx("text-xs font-medium", TONE[item.reading.level])}>{item.reading.label}</span>
            {item.detail && <span className="tnum truncate text-xs text-fg-3">{item.detail}</span>}
          </div>
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
            "h-full",
            tone === "ok" && "bg-fg-3",
            tone === "warn" && "bg-warn",
            tone === "crit" && "bg-crit",
            tone === "unknown" && "bg-hairline"
          )}
          style={{ width: `${Math.min(percent, 100)}%` }}
        />
      </div>
      <span className="tnum w-10 flex-shrink-0 text-right text-xs text-fg">{percent.toFixed(0)}%</span>
      {detail && <span className="tnum hidden w-24 flex-shrink-0 text-right text-xs text-fg-3 sm:block">{detail}</span>}
    </div>
  );
}
