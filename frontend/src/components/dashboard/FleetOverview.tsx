import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { reliabilityApi } from "../../services/api";
import { Section, Panel, StatusDot } from "../ui/Layout";
import { Skeleton } from "../ui/Skeleton";
import { LoadError } from "../ui/LoadError";
import { timeAgo } from "../../lib/format";
import { health, worstLevel, Level } from "../../lib/health";

type Row = {
  id: number;
  name: string;
  os: string | null;
  is_active: boolean;
  last_seen: string | null;
  cpu: number | null;
  memory: number | null;
  disk: number | null;
  open_count: number;
  worst_severity: string | null;
  worst_label: string | null;
  worst_anomaly_id: number | null;
};

const SEV_TONE: Record<string, Level> = { critical: "crit", high: "warn", medium: "warn", low: "ok" };

/** Pior sinal entre os três vitais, ou o do aviso mais grave em aberto. */
function levelOf(row: Row): Level {
  if (row.worst_severity) return SEV_TONE[row.worst_severity] ?? "warn";
  return worstLevel([health.cpu(row.cpu).level, health.memory(row.memory).level, health.disk(row.disk).level]);
}

const LEVEL_ORDER: Record<Level, number> = { crit: 0, warn: 1, unknown: 2, ok: 3 };

/** Todos os computadores numa tela, ordenados por quem precisa de atenção. */
export function FleetOverview({ onSelect }: { onSelect?: (id: number) => void }) {
  const navigate = useNavigate();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState(false);
  const [now, setNow] = useState(Date.now());

  const load = useCallback(() => {
    reliabilityApi
      .fleetOverview()
      .then((r) => {
        setRows(r.data.machines);
        setError(false);
        setNow(Date.now());
      })
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    load();
    const id = window.setInterval(() => !document.hidden && load(), 30000);
    return () => window.clearInterval(id);
  }, [load]);

  if (error) return <LoadError what="a visão geral dos computadores" onRetry={load} />;
  if (!rows) return <Skeleton className="h-32" />;
  // Com um computador só, o painel abaixo já é a visão geral.
  if (rows.length < 2) return null;

  const sorted = [...rows].sort((a, b) => LEVEL_ORDER[levelOf(a)] - LEVEL_ORDER[levelOf(b)]);
  const needAttention = sorted.filter((r) => levelOf(r) !== "ok").length;

  return (
    <Section
      title="Seus computadores"
      description={
        needAttention
          ? `${needAttention} de ${rows.length} ${needAttention === 1 ? "precisa" : "precisam"} de atenção`
          : `${rows.length} computadores, todos dentro do normal`
      }
    >
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {sorted.map((row) => {
          const tone = levelOf(row);
          return (
            <li key={row.id}>
              <button
                type="button"
                onClick={() => (onSelect ? onSelect(row.id) : navigate(`/machines/${row.id}`))}
                className="w-full text-left"
              >
                <Panel className="p-4 transition-colors hover:border-edge">
                  <div className="flex items-baseline justify-between gap-3">
                    <p className="flex min-w-0 items-center gap-2 font-display text-sm font-semibold text-fg">
                      <StatusDot tone={tone === "unknown" ? "idle" : tone} />
                      <span className="truncate">{row.name}</span>
                    </p>
                    {row.open_count > 0 && (
                      <span className="tnum flex-shrink-0 rounded-full bg-warn/15 px-2 py-0.5 font-mono text-micro font-medium text-warn">
                        {row.open_count}
                      </span>
                    )}
                  </div>

                  <dl className="mt-3 grid grid-cols-3 gap-2 text-micro">
                    {([["Proc.", row.cpu], ["Mem.", row.memory], ["Disco", row.disk]] as const).map(([label, value]) => (
                      <div key={label}>
                        <dt className="text-fg-3">{label}</dt>
                        <dd className="tnum font-mono text-sm text-fg">
                          {value == null ? "--" : `${Math.round(value)}%`}
                        </dd>
                      </div>
                    ))}
                  </dl>

                  <p className="mt-3 truncate border-t border-hairline pt-2 text-xs text-fg-2">
                    {!row.is_active
                      ? "Coleta pausada"
                      : row.worst_label
                        ? row.worst_label
                        : row.last_seen
                          ? `Sem novidade · ${timeAgo(row.last_seen, now)}`
                          : "Aguardando a primeira leitura"}
                  </p>
                </Panel>
              </button>
            </li>
          );
        })}
      </ul>
    </Section>
  );
}
