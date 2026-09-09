import { useEffect, useState } from "react";
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine } from "recharts";
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
  /** Linha tracejada marcando onde começa a faixa de atenção. */
  threshold?: number;
  /** Instante a destacar — usado no detalhe do aviso. */
  markAt?: string | null;
}

/** Lê um token de cor do CSS para o Recharts, que não aceita classe utilitária. */
function useToken(name: string) {
  const [value, setValue] = useState("#8a939d");
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
 * Série temporal.
 *
 * Todas as séries usam o mesmo traço neutro: o gráfico existe para mostrar
 * forma e tendência, e dar uma cor diferente a cada métrica só faria o
 * conjunto parecer um mostruário. A única cor é a linha tracejada do limite
 * de atenção — que é informação de estado, não identidade da série.
 */
export function MetricChart({ metrics, dataKey, label, unit = "%", domain, term, threshold, markAt }: MetricChartProps) {
  const line = useToken("fg-2");
  const grid = useToken("hairline");
  const axis = useToken("fg-3");
  const warn = useToken("warn");

  const data = metrics.map((m) => ({
    time: format(new Date(m.timestamp), "HH:mm", { locale: ptBR }),
    value: typeof m[dataKey] === "number" ? Number((m[dataKey] as number).toFixed(1)) : 0,
  }));

  const markTime = markAt ? format(new Date(markAt), "HH:mm", { locale: ptBR }) : null;
  const gradId = `grad-${String(dataKey)}`;

  const CustomTooltip = ({ active, payload, label: l }: any) => {
    if (!active || !payload?.length) return null;
    return (
      <div className="rounded-control border border-edge bg-surface px-2.5 py-1.5 shadow-float">
        <p className="text-micro text-fg-3">{l}</p>
        <p className="tnum text-sm font-medium text-fg">
          {payload[0].value}
          {unit}
        </p>
      </div>
    );
  };

  return (
    <div className="rounded-panel border border-hairline bg-surface px-4 pb-3 pt-3.5">
      <div className="mb-2 flex items-center gap-1.5">
        <h3 className="text-xs text-fg-2">{label}</h3>
        {term && <Explain term={term} />}
      </div>
      <ResponsiveContainer width="100%" height={128}>
        <AreaChart data={data} margin={{ top: 4, right: 4, left: -26, bottom: 0 }}>
          <defs>
            <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={line} stopOpacity={0.14} />
              <stop offset="100%" stopColor={line} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="2 4" stroke={grid} vertical={false} />
          <XAxis
            dataKey="time"
            tick={{ fill: axis, fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
            minTickGap={32}
          />
          <YAxis tick={{ fill: axis, fontSize: 10 }} tickLine={false} axisLine={false} domain={domain || [0, 100]} />
          {threshold !== undefined && (
            <ReferenceLine y={threshold} stroke={warn} strokeDasharray="3 3" strokeWidth={1} />
          )}
          {markTime && <ReferenceLine x={markTime} stroke={warn} strokeWidth={1} />}
          <Tooltip content={<CustomTooltip />} cursor={{ stroke: grid }} />
          <Area type="monotone" dataKey="value" stroke={line} strokeWidth={1.25} fill={`url(#${gradId})`} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
