import { useId } from "react";
import { clsx } from "clsx";
import { Level } from "../../lib/health";

export interface Band {
  /** Início da faixa considerada normal, na unidade da medida. */
  from: number;
  /** Fim da faixa normal — acima disto a leitura entra em atenção. */
  to: number;
}

interface Props {
  values: number[];
  /** Teto do eixo. Percentuais usam 100 para os canais serem comparáveis. */
  max?: number;
  min?: number;
  /** Faixa de comportamento normal desenhada atrás do traço. */
  band?: Band | null;
  /** Estado atual — tinge só o trecho que saiu da faixa. */
  level?: Level;
  height?: number;
  /** Cabeça do traço: onde a leitura está agora. */
  live?: boolean;
  /** Pulso único quando chega leitura nova. Troque a chave para disparar. */
  pulseKey?: number | string;
  /** Posição do evento detectado, de 0 a 1 ao longo do eixo do tempo. */
  eventAt?: number | null;
  animate?: boolean;
  className?: string;
  label?: string;
}

const STROKE: Record<Level, string> = {
  ok: "stroke-ok",
  warn: "stroke-warn",
  crit: "stroke-crit",
  unknown: "stroke-fg-3",
};

const BG: Record<Level, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  crit: "bg-crit",
  unknown: "bg-fg-3",
};

/**
 * O traço de um sinal sobre a faixa do seu comportamento normal.
 *
 * É o elemento de identidade do AnomalyDetect e aparece em toda medida do
 * produto: no canal do painel, na linha de um aviso, no detalhe do evento.
 *
 * A ideia vem do próprio produto — o sistema aprende o que é normal para
 * aquela máquina e percebe quando o sinal sai disso. Então a faixa normal
 * fica desenhada atrás, e o traço só ganha cor no trecho em que a ultrapassa.
 * Uma tela saudável fica inteiramente neutra; um desvio se vê sem legenda e
 * sem precisar saber o que significa "85%".
 */
export function SignalTrace({
  values,
  max,
  min = 0,
  band,
  level = "unknown",
  height = 34,
  live,
  pulseKey,
  eventAt = null,
  animate = true,
  className,
  label,
}: Props) {
  const uid = useId().replace(/:/g, "");
  const points = values.filter((v) => typeof v === "number" && Number.isFinite(v));

  const W = 100;
  const PAD = 2;
  const top = max ?? Math.max(...points, 1);
  const span = Math.max(top - min, 0.0001);
  const y = (v: number) => {
    const clamped = Math.min(Math.max(v, min), top);
    return height - PAD - ((clamped - min) / span) * (height - PAD * 2);
  };

  // Sem sinal, o canal continua desenhado com a linha de base no lugar.
  // Se o componente sumisse, não daria para saber se falta dado ou medida.
  if (points.length < 2) {
    return (
      <div className={clsx("relative w-full", className)} style={{ height }}>
        <svg
          viewBox={`0 0 ${W} ${height}`}
          preserveAspectRatio="none"
          style={{ height, width: "100%" }}
          role="img"
          aria-label={label ?? "Ainda sem leituras suficientes para traçar"}
        >
          <line
            x1="0"
            x2={W}
            y1={height - PAD}
            y2={height - PAD}
            className="stroke-hairline"
            strokeWidth="1"
            strokeDasharray="2 3"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>
    );
  }

  const step = W / (points.length - 1);
  const path = points
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(2)},${y(v).toFixed(2)}`)
    .join(" ");

  const bandTop = band ? y(band.to) : null;
  const bandBottom = band ? y(band.from) : null;
  const breaches = band ? points.some((v) => v > band.to) : false;

  const last = points[points.length - 1];
  const lastY = y(last);
  const tone: Level = level;

  // strokeDasharray fica no style porque é valor de dado; a animação vem da
  // utilitaria, senão o Tailwind não emite o keyframe correspondente.
  const drawStyle = animate ? { strokeDasharray: 1 } : undefined;
  const drawClass = animate ? "animate-draw" : undefined;

  return (
    <div className={clsx("relative w-full", className)} style={{ height }}>
      <svg
        viewBox={`0 0 ${W} ${height}`}
        preserveAspectRatio="none"
        style={{ height, width: "100%" }}
        role="img"
        aria-label={
          label ??
          `Variou de ${points[0].toFixed(0)} a ${last.toFixed(0)}${
            band ? `, com faixa normal até ${band.to}` : ""
          }${breaches ? ". Saiu da faixa normal no período." : ""}`
        }
      >
        <defs>
          {/* Recorte acima da faixa: só o que ultrapassou recebe cor. */}
          {band && bandTop !== null && (
            <clipPath id={`breach-${uid}`}>
              <rect x="0" y="0" width={W} height={Math.max(bandTop, 0)} />
            </clipPath>
          )}
        </defs>


        {/* A faixa do normal. Sem moldura em volta: é um campo, não uma caixa. */}
        {band && bandTop !== null && bandBottom !== null && (
          <>
            <rect
              x="0"
              y={bandTop}
              width={W}
              height={Math.max(bandBottom - bandTop, 0)}
              className="fill-fg-2"
              style={{ opacity: "var(--band-fill)" }}
            />
            <line
              x1="0"
              x2={W}
              y1={bandTop}
              y2={bandTop}
              className="stroke-fg-2"
              style={{ opacity: "var(--band-line)" }}
              strokeWidth="1"
              strokeDasharray="3 3"
              vectorEffect="non-scaling-stroke"
            />
          </>
        )}

        {/* Marca do evento: onde o sistema apontou a anomalia. */}
        {eventAt !== null && eventAt >= 0 && (
          <line
            x1={eventAt * W}
            x2={eventAt * W}
            y1="0"
            y2={height}
            className="stroke-accent"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        )}

        {/* Traço neutro por inteiro. */}
        <path
          d={path}
          fill="none"
          className={clsx("stroke-fg-2", drawClass)}
          strokeWidth="1.5"
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
          pathLength={1}
          style={drawStyle}
        />

        {/* De novo, recortado acima da faixa: o desvio, na cor do estado. */}
        {band && bandTop !== null && breaches && (
          <path
            d={path}
            fill="none"
            clipPath={`url(#breach-${uid})`}
            className={clsx(STROKE[tone], drawClass)}
            strokeWidth="1.75"
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
            pathLength={1}
            style={drawStyle}
          />
        )}
      </svg>

      {/*
        Cabeça do traço e marcador do evento ficam fora do SVG: o viewBox é
        esticado no eixo x, e um círculo dentro dele viraria elipse.
      */}
      {live && (
        <span
          className="pointer-events-none absolute"
          style={{ left: "100%", top: lastY, transform: "translate(-50%, -50%)" }}
          aria-hidden="true"
        >
          <span className="relative flex h-[5px] w-[5px]">
            {pulseKey !== undefined && (
              <span
                key={pulseKey}
                className={clsx("absolute inset-0 animate-ping1 rounded-full", BG[tone])}
              />
            )}
            <span className={clsx("relative h-[5px] w-[5px] rounded-full", BG[tone])} />
          </span>
        </span>
      )}

      {eventAt !== null && eventAt >= 0 && (
        <span
          className="pointer-events-none absolute top-0 -translate-x-1/2 -translate-y-[3px]"
          style={{ left: `${eventAt * 100}%` }}
          aria-hidden="true"
        >
          <svg width="7" height="5" viewBox="0 0 7 5" className="fill-accent">
            <path d="M3.5 5 0 0h7z" />
          </svg>
        </span>
      )}
    </div>
  );
}

/** Ponto de estado. É o principal portador de cor fora dos gráficos. */
export function LiveDot({ tone, breathing }: { tone: Level; breathing?: boolean }) {
  return (
    <span className="relative inline-flex h-1.5 w-1.5" aria-hidden="true">
      <span className={clsx("h-1.5 w-1.5 rounded-full", BG[tone], breathing && "animate-breathe")} />
    </span>
  );
}
