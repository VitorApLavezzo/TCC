import { useState, useCallback, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { anomaliesApi, machinesApi, errorMessage } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { Anomaly, Machine, ANOMALY_TYPE_LABELS } from "../types";
import { AnomalyEvent, AnomalyTimeline } from "../components/AnomalyEvent";
import { Button, TextButton } from "../components/ui/Button";
import { PageHeader } from "../components/ui/Layout";
import { EmptyState } from "../components/ui/EmptyState";
import { ListSkeleton } from "../components/ui/Skeleton";
import { StaleBanner } from "../components/StaleBanner";
import { useToast } from "../components/ui/Toast";
import { pluralize, processName } from "../lib/format";
import { X } from "lucide-react";

const PAGE_SIZE = 25;

const PERIODS = [
  { value: 24, label: "24 horas" },
  { value: 72, label: "3 dias" },
  { value: 168, label: "1 semana" },
  { value: 720, label: "1 mês" },
];

const SEVERITIES = [
  { value: "critical", label: "Crítica" },
  { value: "high", label: "Alta" },
  { value: "medium", label: "Média" },
  { value: "low", label: "Baixa" },
];

export function Anomalies() {
  const navigate = useNavigate();
  const toast = useToast();
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [machines, setMachines] = useState<Machine[]>([]);
  const [machineId, setMachineId] = useState<number | null>(null);
  const [severity, setSeverity] = useState("");
  const [hours, setHours] = useState(72);
  const [unresolvedOnly, setUnresolvedOnly] = useState(false);
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [resolving, setResolving] = useState<number | null>(null);

  useEffect(() => {
    machinesApi
      .list()
      .then((res) => setMachines(res.data))
      .catch(() => {});
  }, []);

  const machineName = useCallback(
    (id: number) => machines.find((m) => m.id === id)?.name ?? `Computador ${id}`,
    [machines]
  );

  const fetchAnomalies = useCallback(async () => {
    const res = await anomaliesApi.list({
      machine_id: machineId ?? undefined,
      hours,
      severity: severity || undefined,
      unresolved_only: unresolvedOnly,
    });
    setAnomalies(res.data);
  }, [machineId, hours, severity, unresolvedOnly]);

  const poll = usePolling(fetchAnomalies, 30000);

  // Mudança de filtro volta à primeira página, senão a pessoa fica numa página
  // que já não existe no novo resultado.
  useEffect(() => setPage(1), [machineId, hours, severity, unresolvedOnly, query]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return anomalies;
    return anomalies.filter((a) => {
      const label = (ANOMALY_TYPE_LABELS[a.anomaly_type] || a.anomaly_type).toLowerCase();
      return (
        label.includes(q) ||
        processName(a)?.toLowerCase().includes(q) ||
        a.explanation?.summary?.toLowerCase().includes(q) ||
        machineName(a.machine_id).toLowerCase().includes(q)
      );
    });
  }, [anomalies, query, machineName]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageItems = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Filtros ativos ficam à vista. Antes, um filtro esquecido produzia uma lista
  // vazia que parecia "o sistema não está detectando nada".
  const activeFilters = [
    machineId !== null && { key: "machine", label: machineName(machineId), clear: () => setMachineId(null) },
    severity && {
      key: "severity",
      label: SEVERITIES.find((s) => s.value === severity)?.label ?? severity,
      clear: () => setSeverity(""),
    },
    hours !== 72 && {
      key: "hours",
      label: PERIODS.find((p) => p.value === hours)?.label ?? `${hours}h`,
      clear: () => setHours(72),
    },
    unresolvedOnly && { key: "unresolved", label: "Só em aberto", clear: () => setUnresolvedOnly(false) },
    query.trim() && { key: "query", label: `“${query.trim()}”`, clear: () => setQuery("") },
  ].filter(Boolean) as { key: string; label: string; clear: () => void }[];

  const clearAll = () => {
    setMachineId(null);
    setSeverity("");
    setHours(72);
    setUnresolvedOnly(false);
    setQuery("");
  };

  const handleResolve = async (e: React.MouseEvent, a: Anomaly) => {
    e.stopPropagation();
    setResolving(a.id);
    try {
      await anomaliesApi.resolve(a.id, !a.is_resolved);
      await fetchAnomalies();
      toast.success(a.is_resolved ? "Aviso reaberto." : "Aviso resolvido.");
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível mudar o estado deste aviso."), "Tente de novo em alguns segundos.");
    } finally {
      setResolving(null);
    }
  };

  const openCount = anomalies.filter((a) => !a.is_resolved).length;

  return (
    <div className="space-y-6">
      <StaleBanner onRetry={poll.refresh} />

      <PageHeader
        title="Avisos"
        description={
          openCount > 0
            ? `${pluralize(openCount, "aviso em aberto", "avisos em aberto")} no período selecionado.`
            : "Tudo que o sistema detectou fora do normal. Nada em aberto no momento."
        }
      />

      {/* Barra de filtros: uma linha só, controles do mesmo tamanho. */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar por tipo, programa ou computador"
            aria-label="Buscar avisos"
            className="h-8 min-w-[220px] flex-1 rounded-control border border-edge bg-surface px-2.5 text-sm text-fg placeholder:text-fg-3 focus:border-accent"
          />
          <select
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            aria-label="Período"
            className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
          >
            {PERIODS.map((p) => (
              <option key={p.value} value={p.value}>
                Últimas {p.label}
              </option>
            ))}
          </select>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            aria-label="Severidade"
            className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
          >
            <option value="">Qualquer severidade</option>
            {SEVERITIES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
          {machines.length > 1 && (
            <select
              value={machineId ?? ""}
              onChange={(e) => setMachineId(e.target.value ? Number(e.target.value) : null)}
              aria-label="Computador"
              className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
            >
              <option value="">Todos os computadores</option>
              {machines.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          )}
          <label className="flex h-8 cursor-pointer items-center gap-2 px-1 text-sm text-fg-2">
            <input
              type="checkbox"
              checked={unresolvedOnly}
              onChange={(e) => setUnresolvedOnly(e.target.checked)}
              className="h-3.5 w-3.5 rounded border-edge bg-surface accent-accent"
            />
            Só em aberto
          </label>
        </div>

        {activeFilters.length > 0 && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-fg-3">
            <span>Filtrando por</span>
            {activeFilters.map((f) => (
              <button
                key={f.key}
                type="button"
                onClick={f.clear}
                className="inline-flex items-center gap-1 rounded text-fg-2 transition-colors hover:text-fg"
              >
                {f.label}
                <X size={11} aria-hidden="true" />
                <span className="sr-only">Remover este filtro</span>
              </button>
            ))}
            <TextButton onClick={clearAll}>Limpar tudo</TextButton>
          </div>
        )}
      </div>

      {poll.initialLoading ? (
        <ListSkeleton rows={5} />
      ) : pageItems.length === 0 ? (
        activeFilters.length > 0 ? (
          <EmptyState
            title="Nenhum aviso corresponde a esses filtros"
            body="Há avisos registrados, mas nenhum dentro do que você filtrou. Amplie o período ou limpe os filtros."
            action={
              <Button variant="primary" onClick={clearAll}>
                Limpar os filtros
              </Button>
            }
          />
        ) : (
          <EmptyState
            title="Nenhum aviso neste período"
            body="Seus computadores não apresentaram nada fora do normal. O sistema continua verificando a cada 30 segundos."
          />
        )
      ) : (
        <div className="space-y-4">
          <p className="tnum text-xs text-fg-3">
            {filtered.length === anomalies.length
              ? pluralize(filtered.length, "aviso", "avisos")
              : `${filtered.length} de ${anomalies.length} avisos`}
            {totalPages > 1 && ` · página ${page} de ${totalPages}`}
          </p>

          {/*
            A mesma fita de eventos do painel: horário à esquerda, tique na
            calha, conteúdo à direita. Ler a página de cima a baixo é percorrer
            a linha do tempo das detecções.
          */}
          <AnomalyTimeline>
            {pageItems.map((a) => (
              <AnomalyEvent
                key={a.id}
                anomaly={a}
                machineName={machines.length > 1 ? machineName(a.machine_id) : undefined}
                onOpen={() => navigate(`/anomalies/${a.id}`)}
                action={
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={resolving === a.id}
                    loadingLabel="..."
                    onClick={(e) => handleResolve(e, a)}
                    aria-label={a.is_resolved ? "Reabrir este aviso" : "Marcar este aviso como resolvido"}
                  >
                    {a.is_resolved ? "Reabrir" : "Resolver"}
                  </Button>
                }
              />
            ))}
          </AnomalyTimeline>

          {totalPages > 1 && (
            <nav aria-label="Páginas de avisos" className="flex items-center justify-between gap-3">
              <Button size="sm" variant="secondary" disabled={page === 1} onClick={() => setPage((p) => p - 1)}>
                Anteriores
              </Button>
              <span className="tnum text-xs text-fg-3">
                {page} de {totalPages}
              </span>
              <Button size="sm" variant="secondary" disabled={page === totalPages} onClick={() => setPage((p) => p + 1)}>
                Próximos
              </Button>
            </nav>
          )}
        </div>
      )}
    </div>
  );
}
