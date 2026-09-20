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
import { useUrlState } from "../hooks/useUrlState";
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
  // Filtros na URL, não no componente: recarregar mantém a visão, o endereço
  // pode ser mandado para alguém e o botão Voltar desfaz o filtro em vez de
  // sair da página.
  const [machineParam, setMachineParam] = useUrlState<string>("computador", "");
  const [severity, setSeverity] = useUrlState<string>("gravidade", "");
  const [hours, setHours] = useUrlState<number>("periodo", 72);
  const [unresolvedOnly, setUnresolvedOnly] = useUrlState<boolean>("abertos", false);
  const [query, setQuery] = useUrlState<string>("busca", "");
  const [page, setPage] = useUrlState<number>("pagina", 1);
  const machineId = machineParam ? Number(machineParam) : null;
  const setMachineId = (id: number | null) => setMachineParam(id ? String(id) : "");
  const [resolving, setResolving] = useState<number | null>(null);
  const [selecionados, setSelecionados] = useState<number[]>([]);
  const [saindo, setSaindo] = useState<number[]>([]);
  const [concluido, setConcluido] = useState<number | null>(null);
  const [emLote, setEmLote] = useState(false);

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

  // Voltar de um aviso devolvia a lista ao topo: com a página na URL, faltava
  // só a altura da rolagem para a pessoa continuar de onde parou.
  useEffect(() => {
    const chave = "anomaliesScroll";
    const salvo = sessionStorage.getItem(chave);
    if (salvo) window.scrollTo(0, Number(salvo));
    const guardar = () => sessionStorage.setItem(chave, String(window.scrollY));
    window.addEventListener("pagehide", guardar);
    return () => {
      guardar();
      window.removeEventListener("pagehide", guardar);
    };
  }, []);

  // Mudança de filtro volta à primeira página, senão a pessoa fica numa página
  // que já não existe no novo resultado.
  useEffect(() => {
    setPage(1);
    setSelecionados([]);
  }, [machineId, hours, severity, unresolvedOnly, query]);  // eslint-disable-line react-hooks/exhaustive-deps

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
      // Confirmação antes do sumiço: o botão vira ✓ e, quando o filtro é "só
      // em aberto", o item recolhe a própria altura em vez de desaparecer de
      // uma vez — sem isso, a lista salta sob o cursor e fica a dúvida de
      // qual linha foi afetada.
      setConcluido(a.id);
      if (unresolvedOnly && !a.is_resolved) {
        setSaindo((atual) => [...atual, a.id]);
        await new Promise((r) => setTimeout(r, 320));
      }
      await fetchAnomalies();
      setSaindo((atual) => atual.filter((id) => id !== a.id));
      setTimeout(() => setConcluido((id) => (id === a.id ? null : id)), 700);
      toast.success(a.is_resolved ? "Aviso reaberto." : "Aviso resolvido.");
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível mudar o estado deste aviso."), "Tente de novo em alguns segundos.");
    } finally {
      setResolving(null);
    }
  };

  const openCount = anomalies.filter((a) => !a.is_resolved).length;

  const alternar = (id: number) =>
    setSelecionados((atual) => (atual.includes(id) ? atual.filter((x) => x !== id) : [...atual, id]));

  const selecionarPagina = () => {
    const ids = pageItems.filter((a) => !a.is_resolved).map((a) => a.id);
    setSelecionados((atual) => (ids.every((id) => atual.includes(id)) ? [] : ids));
  };

  // Em lote a confirmação vem depois, não antes: a ação é reversível, e
  // perguntar "tem certeza?" a cada limpeza de lista é atrito puro.
  const resolverLote = async (reabrir = false) => {
    const ids = [...selecionados];
    if (ids.length === 0) return;
    setEmLote(true);
    try {
      await anomaliesApi.resolveBulk(ids, !reabrir);
      await fetchAnomalies();
      setSelecionados([]);
      toast.undoable(
        `${pluralize(ids.length, "aviso", "avisos")} ${reabrir ? "reaberto(s)" : "resolvido(s)"}.`,
        "Desfazer",
        async () => {
          await anomaliesApi.resolveBulk(ids, reabrir);
          fetchAnomalies();
        }
      );
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível mudar os avisos selecionados."));
    } finally {
      setEmLote(false);
    }
  };

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

      {selecionados.length > 0 && (
        <div className="sticky top-16 z-20 flex flex-wrap items-center justify-between gap-3 rounded-panel border border-edge bg-raised px-4 py-2.5 lg:top-2">
          <p className="text-sm text-fg">
            {pluralize(selecionados.length, "aviso selecionado", "avisos selecionados")}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="primary" loading={emLote} onClick={() => resolverLote(false)}>
              Marcar como resolvidos
            </Button>
            <Button size="sm" variant="secondary" onClick={() => resolverLote(true)}>
              Reabrir
            </Button>
            <Button size="sm" variant="quiet" onClick={() => setSelecionados([])}>
              Limpar seleção
            </Button>
          </div>
        </div>
      )}

      {/* Barra de filtros: uma linha só, com rótulo em cima de cada controle —
          quatro seletores lado a lado sem nome exigiam adivinhar pelo valor. */}
      <div className="space-y-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1">
            <span className="channel-label">Buscar</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar por tipo, programa ou computador"
            aria-label="Buscar avisos"
            className="h-8 min-w-[220px] flex-1 rounded-control border border-edge bg-surface px-2.5 text-sm text-fg placeholder:text-fg-3 focus:border-accent"
          />
          </label>
          <label className="flex flex-col gap-1">
            <span className="channel-label">Período</span>
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
          </label>
          <label className="flex flex-col gap-1">
            <span className="channel-label">Gravidade</span>
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
          </label>
          {machines.length > 1 && (
            <label className="flex flex-col gap-1">
              <span className="channel-label">Computador</span>
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
            </label>
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
        <div className="animate-fade space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="tnum text-xs text-fg-3">
              {filtered.length === anomalies.length
                ? pluralize(filtered.length, "aviso", "avisos")
                : `${filtered.length} de ${anomalies.length} avisos`}
              {totalPages > 1 && ` · página ${page} de ${totalPages}`}
            </p>
            <label className="flex cursor-pointer items-center gap-2 text-xs text-fg-3 hover:text-fg-2">
              <input
                type="checkbox"
                checked={
                  pageItems.some((a) => !a.is_resolved) &&
                  pageItems.filter((a) => !a.is_resolved).every((a) => selecionados.includes(a.id))
                }
                onChange={selecionarPagina}
                className="h-3.5 w-3.5 rounded border-edge bg-surface accent-accent"
              />
              Selecionar os em aberto desta página
            </label>
          </div>

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
                className={saindo.includes(a.id) ? "animate-collapse" : undefined}
                machineName={machines.length > 1 ? machineName(a.machine_id) : undefined}
                onOpen={() => navigate(`/anomalies/${a.id}`)}
                action={
                  <div className="flex items-center gap-2">
                    <label className="flex cursor-pointer items-center p-1" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={selecionados.includes(a.id)}
                        onChange={() => alternar(a.id)}
                        aria-label={`Selecionar o aviso de ${ANOMALY_TYPE_LABELS[a.anomaly_type] || a.anomaly_type}`}
                        className="h-3.5 w-3.5 rounded border-edge bg-surface accent-accent"
                      />
                    </label>
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={resolving === a.id}
                      loadingLabel="..."
                      onClick={(e) => handleResolve(e, a)}
                      aria-label={a.is_resolved ? "Reabrir este aviso" : "Marcar este aviso como resolvido"}
                    >
                      {concluido === a.id ? "✓" : a.is_resolved ? "Reabrir" : "Resolver"}
                    </Button>
                  </div>
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
