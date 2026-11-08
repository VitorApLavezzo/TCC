import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { AlertTriangle, Package, Play, Zap } from "lucide-react";
import { reliabilityApi } from "../../services/api";
import { Section, StatusDot } from "../ui/Layout";
import { severityTone } from "../ui/Badge";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { LoadError } from "../ui/LoadError";

type TimelineEvent = {
  kind: "anomaly" | "change" | "action" | "playbook";
  at: string;
  id: number;
  title: string;
  detail: string | null;
  severity: string | null;
  resolved: boolean | null;
  link: string | null;
};

const ICONS = { anomaly: AlertTriangle, change: Package, action: Play, playbook: Zap };
const LABELS = { anomaly: "Aviso", change: "Mudança", action: "Ação", playbook: "Automação" };

/** Avisos, mudanças, ações e automações desta máquina num eixo só: a história real cruza os quatro. */
export function Timeline({ machineId }: { machineId: number }) {
  const [events, setEvents] = useState<TimelineEvent[] | null>(null);
  const [error, setError] = useState(false);
  const [days, setDays] = useState(30);

  const load = useCallback(() => {
    reliabilityApi
      .timeline(machineId, days)
      .then((r) => {
        setEvents(r.data.events);
        setError(false);
      })
      .catch(() => setError(true));
  }, [machineId, days]);

  useEffect(() => {
    load();
  }, [load]);

  if (error) return <LoadError what="a linha do tempo deste computador" onRetry={load} />;
  if (!events) return <Skeleton className="h-64" />;

  return (
    <Section
      className="animate-fade"
      title="Linha do tempo"
      description="Avisos, mudanças no sistema, ações executadas e automações — na ordem em que aconteceram"
      actions={
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          aria-label="Período da linha do tempo"
          className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
        >
          <option value={7}>7 dias</option>
          <option value={30}>30 dias</option>
          <option value={90}>90 dias</option>
        </select>
      }
    >
      {events.length === 0 ? (
        <EmptyState
          title="Nada registrado neste período"
          body="Quando um aviso aparecer, um programa for instalado ou uma ação for executada, a história fica aqui."
        />
      ) : (
        <ol className="relative space-y-0 border-l border-hairline pl-5">
          {events.map((e) => {
            const Icon = ICONS[e.kind];
            const content = (
              <>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="channel-label">{LABELS[e.kind]}</span>
                  <span className="tnum font-mono text-micro text-fg-3">
                    {e.at ? format(new Date(e.at), "dd/MM HH:mm", { locale: ptBR }) : "--"}
                  </span>
                  {e.kind === "anomaly" && e.resolved && (
                    <span className="text-micro text-fg-3">· resolvido</span>
                  )}
                </div>
                <p className="mt-0.5 text-sm font-medium text-fg">{e.title}</p>
                {e.detail && <p className="mt-0.5 text-xs leading-relaxed text-fg-2">{e.detail}</p>}
              </>
            );
            return (
              <li key={`${e.kind}-${e.id}`} className="relative py-3">
                <span className="absolute -left-[26px] top-4 flex h-3 w-3 items-center justify-center rounded-full bg-canvas">
                  {e.severity ? (
                    <StatusDot tone={severityTone(e.severity)} />
                  ) : (
                    <Icon size={11} className="text-fg-3" aria-hidden="true" />
                  )}
                </span>
                {e.link ? (
                  <Link to={e.link} className="block rounded transition-colors hover:bg-raised">
                    {content}
                  </Link>
                ) : (
                  content
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Section>
  );
}
