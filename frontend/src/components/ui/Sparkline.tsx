/**
 * Histórico recente em uma linha, sem preenchimento.
 *
 * Responde "está subindo ou já estava assim?" sem pedir uma segunda tela. A
 * área preenchida da versão anterior só adicionava massa visual.
 */
export function Sparkline({
  values,
  className,
  height = 20,
  max,
}: {
  values: number[];
  className?: string;
  height?: number;
  /** Teto do eixo. Percentuais usam 100 para as linhas serem comparáveis. */
  max?: number;
}) {
  const points = values.filter((v) => typeof v === "number" && !Number.isNaN(v));
  if (points.length < 2) return <div style={{ height }} aria-hidden="true" />;

  const w = 100;
  const top = max ?? Math.max(...points, 1);
  const step = w / (points.length - 1);
  const y = (v: number) => height - (Math.min(v, top) / top) * (height - 2) - 1;
  const line = points.map((v, i) => `${i * step},${y(v)}`).join(" ");

  const first = points[0];
  const last = points[points.length - 1];

  return (
    <svg
      viewBox={`0 0 ${w} ${height}`}
      preserveAspectRatio="none"
      className={className}
      style={{ height, width: "100%" }}
      role="img"
      aria-label={`Variou de ${first.toFixed(0)} a ${last.toFixed(0)} no período recente`}
    >
      <polyline
        points={line}
        fill="none"
        className="stroke-current"
        strokeWidth="1"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
