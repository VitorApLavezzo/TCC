import { useEffect, useState } from "react";
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ReferenceArea,
} from "recharts";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Metric } from "../../types";
import { Explain } from "../ui/Explain";

interface MetricChartProps {
  metrics: Metric[];
  dataKey: keyof Metric;
  label: string;
  unit?: string;
  domain?: [number, number];
  term?: string;
  /** Onde termina a faixa de comportamento normal desta medida. */
  threshold?: number;
  /** Instante a destacar — usado no detalhe do aviso. */
  markAt?: string | null;
  /** Sem moldura, título nem legenda de limite própria — para uso dentro de um painel com abas. */
  bare?: boolean;
}

/** Lê um token de cor do CSS para o Recharts, que não aceita classe utilitária. */
function useToken(name: string) {
  const [value, setValue] = useState("#7a7a80");
  useEffect(() => {
    const read = () => {
      const raw = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
      if (raw) setValue(`rgb(${raw.split(/\s+/).join(" ")})`);
    };
    read();
    const obs = new MutationObserver(read);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, [name]);
  return value;
}

/**
 * Série temporal, com a mesma gramática do traço dos canais.
 *
 * A faixa do normal é sombreada da base até o limite de atenção, e o traço
 * segue neutro: o que a pessoa procura é a forma saindo da faixa, não uma
 * linha bonita. Nenhuma série ganha cor própria — dar uma cor a cada métrica
 * faria o conjunto parecer um mostruário e roubaria significado do vermelho.
 */
export function MetricChart({
  metrics,
  dataKey,
  label,
  unit = "%",
  domain,
  term,
  threshold,
  markAt,
  bare,
}: MetricChartProps) {
  const line = useToken("fg-2");
  const grid = useToken("hairline");
  const axis = useToken("fg-3");
  const accent = useToken("accent");

  const data = metrics.map((m) => ({
    time: format(new Date(m.timestamp), "HH:mm", { locale: ptBR }),
    value: typeof m[dataKey] === "number" ? Number((m[dataKey] as number).toFixed(1)) : 0,
  }));

  const markTime = markAt ? format(new Date(markAt), "HH:mm", { locale: ptBR }) : null;
  const gradId = `grad-${String(dataKey)}`;
  const yDomain = domain || [0, 100];

  const CustomTooltip = ({ active, payload, label: l }: any) => {
    if (!active || !payload?.length) return null;
    const v = payload[0].value;
    const out = threshold !== undefined && v > threshold;
    return (
      <div className="rounded-control border border-edge bg-surface px-2.5 py-1.5 shadow-float">
        <p className="tnum font-mono text-micro text-fg-3">{l}</p>
        <p className="tnum font-mono text-sm font-medium text-fg">
          {v}
          {unit}
        </p>
        {out && <p className="mt-0.5 text-micro text-warn">acima da faixa normal</p>}
      </div>
    );
  };

  const chart = (
    <>
      <ResponsiveContainer width="100%" height={bare ? 220 : 132}>
        <AreaChart data={data} margin={{ top: 4, right: 4, left: -26, bottom: 0 }}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={line} stopOpacity={0.13} />
              <stop offset="100%" stopColor={line} stopOpacity={0} />
            </linearGradient>
          </defs>

          {/* A faixa do normal, sombreada da base até o limite de atenção. */}
          {threshold !== undefined && (
            <ReferenceArea
              y1={yDomain[0]}
              y2={threshold}
              fill={line}
              fillOpacity={0.05}
              stroke={line}
              strokeOpacity={0.18}
              strokeDasharray="3 3"
              ifOverflow="extendDomain"
            />
          )}

          <CartesianGrid strokeDasharray="2 4" stroke={grid} vertical={false} />
          <XAxis
            dataKey="time"
            tick={{ fill: axis, fontSize: 10, fontFamily: "Red Hat Mono, monospace" }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
            minTickGap={32}
          />
          <YAxis
            tick={{ fill: axis, fontSize: 10, fontFamily: "Red Hat Mono, monospace" }}
            tickLine={false}
            axisLine={false}
            domain={yDomain}
          />

          {/* Marca do evento: mesma íris do tique de detecção no resto do produto. */}
          {markTime && <ReferenceLine x={markTime} stroke={accent} strokeWidth={1.25} />}

          <Tooltip content={<CustomTooltip />} cursor={{ stroke: grid }} />
          <Area type="monotone" dataKey="value" stroke={line} strokeWidth={1.4} fill={`url(#${gradId})`} />
        </AreaChart>
      </ResponsiveContainer>
    </>
  );

  if (bare) return chart;

  return (
    <div className="rounded-panel border border-hairline bg-surface px-4 pb-3 pt-3">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <h3 className="channel-label">{label}</h3>
          {term && <Explain term={term} />}
        </div>
        {threshold !== undefined && (
          <span className="tnum font-mono text-micro text-fg-3">
            normal até {threshold}
            {unit}
          </span>
        )}
      </div>
      {chart}
    </div>
  );
}
