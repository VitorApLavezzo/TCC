import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Metric } from "../../types";

interface MetricChartProps {
  metrics: Metric[];
  dataKey: keyof Metric;
  color: string;
  label: string;
  unit?: string;
  domain?: [number, number];
}

export function MetricChart({ metrics, dataKey, color, label, unit = "%", domain }: MetricChartProps) {
  const data = metrics.map((m) => ({
    time: format(new Date(m.timestamp), "HH:mm", { locale: ptBR }),
    value: typeof m[dataKey] === "number" ? Number((m[dataKey] as number).toFixed(1)) : 0,
  }));

  const CustomTooltip = ({ active, payload, label: l }: any) => {
    if (active && payload?.length) {
      return (
        <div className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-xs">
          <p className="text-gray-400">{l}</p>
          <p className="text-white font-semibold">
            {payload[0].value}{unit}
          </p>
        </div>
      );
    }
    return null;
  };

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
      <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-4">{label}</h3>
      <ResponsiveContainer width="100%" height={160}>
        <AreaChart data={data} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id={`grad-${dataKey as string}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={color} stopOpacity={0.3} />
              <stop offset="95%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            dataKey="time"
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickLine={false}
            axisLine={false}
            domain={domain || [0, 100]}
          />
          <Tooltip content={<CustomTooltip />} />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={2}
            fill={`url(#grad-${dataKey as string})`}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
