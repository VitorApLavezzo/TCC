import { useState, useCallback, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { anomaliesApi, metricsApi, machinesApi } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { useWebSocket } from "../hooks/useWebSocket";
import { Machine, Metric, Anomaly, LearningStatus, ANOMALY_TYPE_LABELS } from "../types";
import { Verdict } from "../components/Verdict";
import { FreshnessTag } from "../components/FreshnessTag";
import { StaleBanner } from "../components/StaleBanner";
import { MetricChart } from "../components/charts/MetricChart";
import { Severity } from "../components/ui/Badge";
import { PageHeader, Section, Panel, DataList, DataRow, StatusDot } from "../components/ui/Layout";
import { VitalStrip, VitalItem, Meter } from "../components/ui/VitalStrip";
import { Explain } from "../components/ui/Explain";
import { Button, TextButton } from "../components/ui/Button";
import { EmptyState } from "../components/ui/EmptyState";
import { VitalsSkeleton, Skeleton } from "../components/ui/Skeleton";
import { health, toneOf, worstLevel } from "../lib/health";
import { bytesPerSec, formatUptime, gigabytes, pluralize, timeAgo } from "../lib/format";
import { useStatus } from "../context/StatusContext";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";

const MAX_CHART_POINTS = 60;

export function Dashboard() {
  const navigate = useNavigate();
  const { now } = useStatus();
  const [machines, setMachines] = useState<Machine[]>([]);
  const [selectedMachine, setSelectedMachine] = useState<number | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [latestMetric, setLatestMetric] = useState<Metric | null>(null);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [learning, setLearning] = useState<LearningStatus | null>(null);
  const [switching, setSwitching] = useState(false);
  const selectedRef = useRef<number | null>(null);
  selectedRef.current = selectedMachine;

  const fetchAll = useCallback(async () => {
    const [machRes, anomRes] = await Promise.all([machinesApi.list(), anomaliesApi.list({ hours: 24 })]);
    const machineList: Machine[] = machRes.data;
    setMachines(machineList);
    setAnomalies(anomRes.data);

    const first = selectedRef.current ?? machineList.find((m) => m.is_active)?.id ?? machineList[0]?.id ?? null;
    if (!selectedRef.current && first) setSelectedMachine(first);
  }, []);

  const poll = usePolling(fetchAll, 60000);

  // Troca de máquina: busca imediata, com esqueleto no lugar dos dados da
  // anterior. Antes a tela ficava vazia e parecia que a máquina não tinha dados.
  useEffect(() => {
    if (!selectedMachine) return;
    let cancelled = false;
    setSwitching(true);
    setMetrics([]);
    setLatestMetric(null);
    setLearning(null);

    Promise.all([
      metricsApi.list(selectedMachine, 3).catch(() => ({ data: [] })),
      metricsApi.latest(selectedMachine).catch(() => ({ data: null })),
      metricsApi.learning(selectedMachine).catch(() => ({ data: null })),
    ])
      .then(([mRes, lRes, learnRes]) => {
        if (cancelled) return;
        setMetrics((mRes.data as Metric[]).slice(-MAX_CHART_POINTS));
        setLatestMetric(lRes.data);
        setLearning(learnRes.data);
      })
      .finally(() => !cancelled && setSwitching(false));

    return () => {
      cancelled = true;
    };
  }, [selectedMachine]);

  const wsStatus = useWebSocket(selectedMachine ? `/ws/machine/${selectedMachine}` : null, (msg) => {
    if (msg.type === "metric") {
      const m = msg.data as Metric;
      setLatestMetric(m);
      setMetrics((prev) => [...prev, m].slice(-MAX_CHART_POINTS));
      setLearning((prev) => (prev ? { ...prev, collected: prev.collected + 1 } : prev));
    }
    if (msg.type === "anomaly") {
      anomaliesApi
        .list({ hours: 24 })
        .then((r) => setAnomalies(r.data))
        .catch(() => {});
    }
  });

  const machine = machines.find((m) => m.id === selectedMachine) ?? null;
  const lm = latestMetric;
  const gpu = lm?.gpu_metrics?.[0];
  const hasBattery = lm?.battery_percent !== null && lm?.battery_percent !== undefined;
  const cores = lm?.cpu_count_logical ?? null;

  const cpuTemp = (() => {
    if (!lm?.temperatures) return null;
    const entries = Object.values(lm.temperatures as Record<string, any[]>).flat();
    const entry = entries.find((e: any) => e?.current > 0);
    return entry ? (entry as any).current : null;
  })();

  const series = (key: keyof Metric) => metrics.map((m) => (typeof m[key] === "number" ? (m[key] as number) : 0));

  const cpu = health.cpu(lm?.cpu_percent);
  const mem = health.memory(lm?.mem_percent);
  const disk = health.disk(lm?.disk_percent);
  const swap = health.swap(lm?.swap_percent);
  const temp = health.cpuTemp(cpuTemp);
  const load = health.loadAvg(lm?.load_avg_1, cores);

  const overall = worstLevel([cpu, mem, disk, swap, temp, load].map((r) => r.level));
  const machineAnomalies = anomalies.filter((a) => !selectedMachine || a.machine_id === selectedMachine);
  const openAnomalies = machineAnomalies.filter((a) => !a.is_resolved);

  // Quatro medidas, escolhidas por relevância — não por quantas cabem na tela.
  // A quarta é temperatura quando o sensor existe, senão memória virtual.
  const vitals: VitalItem[] = lm
    ? [
        {
          label: "Processador",
          term: "cpu",
          value: lm.cpu_percent?.toFixed(0) ?? "--",
          unit: "%",
          reading: cpu,
          history: series("cpu_percent"),
          historyMax: 100,
          detail: lm.cpu_freq_current ? `${(lm.cpu_freq_current / 1000).toFixed(1)} GHz` : undefined,
        },
        {
          label: "Memória",
          term: "memoria",
          value: lm.mem_percent?.toFixed(0) ?? "--",
          unit: "%",
          reading: mem,
          history: series("mem_percent"),
          historyMax: 100,
          detail: lm.mem_total ? `${gigabytes(lm.mem_used)} / ${gigabytes(lm.mem_total, 0)}` : undefined,
        },
        {
          label: "Disco",
          term: "disco",
          value: lm.disk_percent?.toFixed(0) ?? "--",
          unit: "%",
          reading: disk,
          history: series("disk_percent"),
          historyMax: 100,
          detail: lm.disk_free ? `${gigabytes(lm.disk_free, 0)} livres` : undefined,
        },
        cpuTemp !== null
          ? {
              label: "Temperatura",
              term: "temperatura",
              value: cpuTemp.toFixed(0),
              unit: "°C",
              reading: temp,
            }
          : {
              label: "Memória virtual",
              term: "swap",
              value: lm.swap_percent?.toFixed(0) ?? "--",
              unit: "%",
              reading: swap,
              history: series("swap_percent"),
              historyMax: 100,
              detail: lm.swap_total ? `de ${gigabytes(lm.swap_total, 0)}` : undefined,
            },
      ]
    : [];

  if (poll.initialLoading) {
    return (
      <div className="space-y-8">
        <Skeleton className="h-8 w-40" />
        <VitalsSkeleton />
      </div>
    );
  }

  if (machines.length === 0) {
    return (
      <div className="space-y-6">
        <StaleBanner onRetry={poll.refresh} />
        <PageHeader title="Painel" description="A saúde dos computadores que você monitora." />
        <EmptyState
          title="Nenhum computador conectado"
          body="Conecte o primeiro para começar a acompanhar. Leva cerca de dois minutos e não exige conhecimento técnico."
          action={
            <Button variant="primary" onClick={() => navigate("/welcome")}>
              Conectar um computador
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <StaleBanner onRetry={poll.refresh} />

      <PageHeader
        title="Painel"
        aside={
          machines.length > 1 ? (
            <label className="flex items-center gap-2 text-xs text-fg-2">
              <span className="sr-only sm:not-sr-only">Computador</span>
              <select
                value={selectedMachine ?? ""}
                onChange={(e) => setSelectedMachine(Number(e.target.value))}
                className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
              >
                {machines.map((m) => {
                  const pend = anomalies.filter((a) => a.machine_id === m.id && !a.is_resolved).length;
                  return (
                    <option key={m.id} value={m.id}>
                      {m.name}
                      {pend > 0 ? ` (${pend})` : ""}
                    </option>
                  );
                })}
              </select>
            </label>
          ) : undefined
        }
      />

      <div className="space-y-5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
          <p className="text-sm font-medium text-fg">{machine?.name}</p>
          <FreshnessTag
            lastMetricAt={lm?.timestamp ?? machine?.last_seen}
            wsStatus={wsStatus}
            paused={machine ? !machine.is_active : false}
          />
        </div>

        <Verdict
          level={overall}
          openAnomalies={openAnomalies}
          learning={learning}
          onOpenAnomaly={(id) => navigate(`/anomalies/${id}`)}
          onSeeAll={() => navigate("/anomalies")}
        />

        {switching ? <VitalsSkeleton /> : lm && <VitalStrip items={vitals} />}
      </div>

      {!switching && !lm && (
        <EmptyState
          title="Este computador ainda não enviou leituras"
          body="Confira se ele está ligado, com internet, e se o agente foi instalado. A primeira leitura chega em até 30 segundos depois disso."
          action={
            <Button variant="secondary" onClick={() => navigate("/machines")}>
              Ver instruções de instalação
            </Button>
          }
        />
      )}

      {lm && !switching && (
        <>
          <Section title="Detalhes">
            <Panel className="grid grid-cols-1 divide-y divide-hairline md:grid-cols-3 md:divide-x md:divide-y-0">
              <div className="px-5 py-4">
                <p className="mb-1 text-xs font-medium text-fg-3">Sistema</p>
                <DataList>
                  <DataRow label="Ligado há" value={formatUptime(lm.uptime_seconds)} hint={<Explain term="uptime" />} />
                  <DataRow
                    label="Programas rodando"
                    value={lm.process_count ?? "--"}
                    hint={<Explain term="processos" />}
                  />
                  <DataRow
                    label="Fila do processador"
                    value={lm.load_avg_1?.toFixed(2) ?? "--"}
                    note={load.label}
                    tone={toneOf(load)}
                    hint={<Explain term="load" />}
                  />
                  {cores && <DataRow label="Núcleos" value={cores} />}
                </DataList>
              </div>

              <div className="px-5 py-4">
                <p className="mb-1 text-xs font-medium text-fg-3">Rede e disco</p>
                <DataList>
                  <DataRow label="Enviando" value={bytesPerSec(lm.net_bytes_sent)} />
                  <DataRow label="Recebendo" value={bytesPerSec(lm.net_bytes_recv)} />
                  <DataRow
                    label="Conexões abertas"
                    value={lm.net_connections ?? "--"}
                    hint={<Explain term="conexoes" />}
                  />
                  <DataRow label="Lendo do disco" value={bytesPerSec(lm.disk_read_bytes)} />
                  <DataRow label="Gravando no disco" value={bytesPerSec(lm.disk_write_bytes)} />
                </DataList>
              </div>

              <div className="px-5 py-4">
                <p className="mb-1 text-xs font-medium text-fg-3">
                  {hasBattery ? "Bateria" : gpu ? "Placa de vídeo" : "Memória virtual"}
                </p>
                <DataList>
                  {hasBattery ? (
                    <>
                      <DataRow
                        label="Carga"
                        value={`${lm.battery_percent?.toFixed(0)}%`}
                        note={lm.battery_plugged ? "na tomada" : health.battery(lm.battery_percent).label}
                        tone={lm.battery_plugged ? undefined : toneOf(health.battery(lm.battery_percent))}
                      />
                      {!lm.battery_plugged && lm.battery_secs_left != null && (
                        <DataRow
                          label="Uso restante"
                          value={`${Math.floor(lm.battery_secs_left / 3600)}h${String(
                            Math.floor((lm.battery_secs_left % 3600) / 60)
                          ).padStart(2, "0")}`}
                        />
                      )}
                      {lm.battery_health_percent != null && (
                        <DataRow
                          label="Saúde"
                          value={`${lm.battery_health_percent.toFixed(0)}%`}
                          note={health.batteryHealth(lm.battery_health_percent).label}
                          tone={toneOf(health.batteryHealth(lm.battery_health_percent))}
                          hint={<Explain term="saude_bateria" />}
                        />
                      )}
                      {lm.battery_cycle_count != null && (
                        <DataRow label="Ciclos de carga" value={lm.battery_cycle_count} hint={<Explain term="ciclos" />} />
                      )}
                    </>
                  ) : gpu ? (
                    <>
                      <DataRow
                        label="Uso"
                        value={`${gpu.load_percent?.toFixed(0) ?? "--"}%`}
                        note={health.gpuLoad(gpu.load_percent).label}
                        tone={toneOf(health.gpuLoad(gpu.load_percent))}
                      />
                      <DataRow
                        label="Memória de vídeo"
                        value={`${gpu.mem_percent?.toFixed(0) ?? "--"}%`}
                        hint={<Explain term="vram" />}
                      />
                      <DataRow label="Temperatura" value={`${gpu.temperature?.toFixed(0) ?? "--"} °C`} />
                      <DataRow label="Modelo" value={gpu.name} />
                    </>
                  ) : (
                    <DataRow
                      label="Em uso"
                      value={`${lm.swap_percent?.toFixed(0) ?? "--"}%`}
                      note={swap.label}
                      tone={toneOf(swap)}
                      hint={<Explain term="swap" />}
                    />
                  )}
                </DataList>
              </div>
            </Panel>

            {/* GPU e bateria coexistem em notebook com placa dedicada: a terceira
                coluna mostra a bateria e a placa vem numa linha própria. */}
            {hasBattery && gpu && (
              <Panel className="mt-3 px-5 py-4">
                <p className="mb-1 text-xs font-medium text-fg-3">Placa de vídeo — {gpu.name}</p>
                <DataList className="md:grid md:grid-cols-3 md:gap-x-8 md:divide-y-0">
                  <DataRow
                    label="Uso"
                    value={`${gpu.load_percent?.toFixed(0) ?? "--"}%`}
                    note={health.gpuLoad(gpu.load_percent).label}
                    tone={toneOf(health.gpuLoad(gpu.load_percent))}
                  />
                  <DataRow
                    label="Memória de vídeo"
                    value={`${gpu.mem_percent?.toFixed(0) ?? "--"}%`}
                    hint={<Explain term="vram" />}
                  />
                  <DataRow label="Temperatura" value={`${gpu.temperature?.toFixed(0) ?? "--"} °C`} />
                </DataList>
              </Panel>
            )}

            {lm.disk_partitions && lm.disk_partitions.length > 1 && (
              <Panel className="mt-3 px-5 py-4">
                <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-fg-3">
                  Divisões do disco
                  <Explain term="particoes" />
                </p>
                {lm.disk_partitions.map((p) => (
                  <Meter
                    key={p.mountpoint}
                    label={p.mountpoint}
                    percent={p.percent}
                    reading={health.disk(p.percent)}
                    detail={`${p.free_gb.toFixed(0)} GB livres`}
                  />
                ))}
              </Panel>
            )}
          </Section>

          {metrics.length > 1 && (
            <Section
              title="Últimas horas"
              description={`${metrics.length} leituras · a mais recente ${timeAgo(lm.timestamp, now)}`}
            >
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <MetricChart metrics={metrics} dataKey="cpu_percent" label="Processador (%)" term="cpu" threshold={80} />
                <MetricChart metrics={metrics} dataKey="mem_percent" label="Memória (%)" term="memoria" threshold={85} />
                <MetricChart metrics={metrics} dataKey="disk_percent" label="Disco (%)" term="disco" threshold={85} />
                <MetricChart
                  metrics={metrics}
                  dataKey="net_connections"
                  label="Conexões de rede"
                  unit=""
                  term="conexoes"
                  domain={[0, Math.max(...metrics.map((m) => m.net_connections ?? 0)) + 10]}
                />
              </div>
            </Section>
          )}
        </>
      )}

      <Section
        title="Avisos recentes"
        description="Últimas 24 horas"
        actions={machineAnomalies.length > 0 ? <TextButton onClick={() => navigate("/anomalies")}>Ver todos</TextButton> : undefined}
      >
        {machineAnomalies.length === 0 ? (
          <p className="py-2 text-sm text-fg-2">
            Nenhum aviso nas últimas 24 horas.{" "}
            <span className="text-fg-3">
              {learning && !learning.ml_ready
                ? "A detecção ainda está aprendendo o normal deste computador."
                : "O sistema verifica a cada 30 segundos."}
            </span>
          </p>
        ) : (
          <ul className="divide-y divide-hairline">
            {machineAnomalies.slice(0, 6).map((a) => (
              <li key={a.id}>
                <button
                  type="button"
                  onClick={() => navigate(`/anomalies/${a.id}`)}
                  className="-mx-2 flex w-[calc(100%+1rem)] items-baseline gap-3 rounded-control px-2 py-2.5 text-left transition-colors hover:bg-sunken"
                >
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
                      <span className="text-sm text-fg">{ANOMALY_TYPE_LABELS[a.anomaly_type] || a.anomaly_type}</span>
                      {a.is_resolved ? (
                        <span className="flex items-center gap-1.5 text-xs text-fg-3">
                          <StatusDot tone="idle" />
                          Resolvida
                        </span>
                      ) : (
                        <Severity severity={a.severity} />
                      )}
                    </span>
                    {a.explanation?.summary && (
                      <span className="clamp-2 mt-0.5 block text-xs leading-relaxed text-fg-2">
                        {a.explanation.summary}
                      </span>
                    )}
                  </span>
                  <span className="tnum flex-shrink-0 text-xs text-fg-3">
                    {format(new Date(a.detected_at), "dd/MM HH:mm", { locale: ptBR })}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Section>

      {machines.length > 1 && (
        <p className="text-xs text-fg-3">
          {pluralize(machines.length, "computador conectado", "computadores conectados")} ·{" "}
          <TextButton onClick={() => navigate("/machines")}>gerenciar</TextButton>
        </p>
      )}
    </div>
  );
}
