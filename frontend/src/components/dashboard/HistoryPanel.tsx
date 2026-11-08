import { useState } from "react";
import { clsx } from "clsx";
import { Metric } from "../../types";
import { MetricChart } from "../charts/MetricChart";
import { Panel } from "../ui/Layout";
import { THRESHOLDS } from "../../lib/health";
import { timeAgo } from "../../lib/format";

/** Histórico das últimas horas, um gráfico por aba; a lógica das abas vive só aqui. */
export function HistoryPanel({
  metrics,
  lastTimestamp,
  now,
  className,
}: {
  metrics: Metric[];
  lastTimestamp: string;
  now: number;
  className?: string;
}) {
  const [tab, setTab] = useState(0);

  const tabs: {
    key: keyof Metric;
    label: string;
    term?: string;
    unit: string;
    threshold?: number;
    domain?: [number, number];
  }[] = [
    { key: "cpu_percent", label: "Processador", term: "cpu", unit: "%", threshold: THRESHOLDS.cpu.warn },
    { key: "mem_percent", label: "Memória", term: "memoria", unit: "%", threshold: THRESHOLDS.memory.warn },
    { key: "disk_percent", label: "Disco", term: "disco", unit: "%", threshold: THRESHOLDS.disk.warn },
    {
      key: "net_connections",
      label: "Conexões",
      term: "conexoes",
      unit: "",
      domain: [0, Math.max(...metrics.map((m) => m.net_connections ?? 0), 0) + 10],
    },
  ];

  const activeTab = tabs[Math.min(tab, tabs.length - 1)];
  const series = metrics
    .map((m) => (typeof m[activeTab.key] === "number" ? (m[activeTab.key] as number) : null))
    .filter((v): v is number => v !== null);
  const latest = series.length ? Math.round(series[series.length - 1]) : null;
  const minValue = series.length ? Math.round(Math.min(...series)) : null;
  const maxValue = series.length ? Math.round(Math.max(...series)) : null;

  return (
    <Panel className={clsx("p-5", className)}>
      <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="font-display text-md font-semibold text-fg">Últimas horas</h3>
          <p className="mt-0.5 text-xs text-fg-3">
            {metrics.length} leituras · a mais recente {timeAgo(lastTimestamp, now)}
          </p>
        </div>
        {/* Só a aba ativa entra no Tab; as outras se alcançam pelas setas. */}
        <div
          role="tablist"
          aria-label="Medida do gráfico"
          onKeyDown={(e) => {
            if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
            e.preventDefault();
            const next = (tab + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
            setTab(next);
            const buttons = e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]');
            requestAnimationFrame(() => buttons[next]?.focus());
          }}
          className="inline-flex max-w-full gap-0.5 overflow-x-auto rounded-control border border-hairline bg-canvas p-1"
        >
          {tabs.map((t, i) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={i === tab}
              tabIndex={i === tab ? 0 : -1}
              onClick={() => setTab(i)}
              className={clsx(
                "flex-shrink-0 whitespace-nowrap rounded-[7px] px-3 py-1.5 text-xs font-medium transition-colors",
                i === tab ? "bg-surface text-fg shadow-raise" : "text-fg-2 hover:text-fg"
              )}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <MetricChart
        bare
        metrics={metrics}
        dataKey={activeTab.key}
        label={activeTab.label}
        unit={activeTab.unit}
        term={activeTab.term}
        threshold={activeTab.threshold}
        domain={activeTab.domain}
      />

      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-fg-2">
        <span>
          Agora <b className="tnum font-mono font-medium text-fg">{latest ?? "--"}{activeTab.unit}</b>
        </span>
        <span>
          Mínimo <b className="tnum font-mono font-medium text-fg">{minValue ?? "--"}{activeTab.unit}</b>
        </span>
        <span>
          Máximo <b className="tnum font-mono font-medium text-fg">{maxValue ?? "--"}{activeTab.unit}</b>
        </span>
        {activeTab.threshold !== undefined && (
          <span>
            Limite de atenção{" "}
            <b className="tnum font-mono font-medium text-fg">
              {activeTab.threshold}
              {activeTab.unit}
            </b>
          </span>
        )}
      </div>
    </Panel>
  );
}
