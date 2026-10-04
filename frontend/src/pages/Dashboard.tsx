import { useState, useCallback, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { anomaliesApi, metricsApi, machinesApi } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { useWebSocket } from "../hooks/useWebSocket";
import { Machine, Metric, Anomaly, LearningStatus, LearnedBaseline } from "../types";
import { Verdict } from "../components/Verdict";
import { AnomalyEvent, AnomalyTimeline } from "../components/AnomalyEvent";
import { FreshnessTag } from "../components/FreshnessTag";
import { StaleBanner } from "../components/StaleBanner";
import { HistoryPanel } from "../components/dashboard/HistoryPanel";
import { PendingRuns } from "../components/automation/PendingRuns";
import { FleetOverview } from "../components/dashboard/FleetOverview";
import { NextSteps } from "../components/dashboard/NextSteps";
import { PageHeader, Panel, PanelLabel, DataList, DataRow } from "../components/ui/Layout";
import { VitalStrip, VitalItem, Meter } from "../components/ui/VitalStrip";
import { Explain } from "../components/ui/Explain";
import { Button, TextButton } from "../components/ui/Button";
import { DiagnoseButton } from "../components/DiagnoseButton";
import { FocusModeControl } from "../components/FocusModeControl";
import { EmptyState } from "../components/ui/EmptyState";
import { VitalsSkeleton, Skeleton } from "../components/ui/Skeleton";
import { health, toneOf, worstLevel, bandFor, THRESHOLDS, Level } from "../lib/health";
import { bytesPerSec, formatUptime, gigabytes, pluralize } from "../lib/format";
import { useStatus } from "../context/StatusContext";

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
  const [baseline, setBaseline] = useState<LearnedBaseline | null>(null);
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
    setBaseline(null);

    Promise.all([
      metricsApi.list(selectedMachine, 3).catch(() => ({ data: [] })),
      metricsApi.latest(selectedMachine).catch(() => ({ data: null })),
      metricsApi.learning(selectedMachine).catch(() => ({ data: null })),
      metricsApi.baseline(selectedMachine).catch(() => ({ data: null })),
    ])
      .then(([mRes, lRes, learnRes, baseRes]) => {
        if (cancelled) return;
        setMetrics((mRes.data as Metric[]).slice(-MAX_CHART_POINTS));
        setLatestMetric(lRes.data);
        setLearning(learnRes.data);
        setBaseline(baseRes.data?.ready ? baseRes.data : null);
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

  /**
   * A faixa desenhada atrás do traço: o normal APRENDIDO desta máquina nesta
   * hora, quando já houver histórico suficiente; senão, o limite fixo de saúde.
   *
   * Um servidor que vive em 70% de CPU e um notebook que vive em 5% têm
   * "normais" diferentes — e o mesmo notebook tem um normal às 3h e outro às
   * 15h. Sair dessa faixa significa "diferente do seu normal", que não é
   * "perigoso": por isso o desvio só ganha cor de estado quando a leitura
   * também passa do limite de saúde (`breachTone`).
   */
  const bandOf = (key: string, fallback: keyof typeof THRESHOLDS, reading: { level: string }) => {
    const learned = baseline?.metrics?.[key]?.now;
    if (!learned || learned.fallback) {
      return { band: bandFor(fallback), breachTone: undefined, bandLabel: undefined };
    }
    // Uma margem pequena evita que a oscilação normal pinte o traço o tempo todo
    const top = Math.min(Math.max(learned.p95, learned.p50 + 3, 3), 100);
    return {
      band: { from: 0, to: top },
      breachTone: (reading.level === "ok" || reading.level === "unknown" ? "unknown" : reading.level) as Level,
      bandLabel: `normal daqui às ${String(baseline!.current_hour).padStart(2, "0")}h: até ${top.toFixed(0)}%`,
    };
  };

  // Quatro medidas, escolhidas por relevância — não por quantas cabem na tela.
  // A quarta é temperatura quando o sensor existe, senão memória virtual.
  // A cabeça do traço só é "ao vivo" enquanto o WebSocket estiver aberto; a
  // chave de pulso muda a cada leitura e dispara um único anel no ponto.
  const liveHead = wsStatus === "open";
  const pulseKey = lm?.timestamp;

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
          limit: THRESHOLDS.cpu.warn,
          critAt: THRESHOLDS.cpu.crit,
          ...bandOf("cpu", "cpu", cpu),
          live: liveHead,
          pulseKey,
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
          limit: THRESHOLDS.memory.warn,
          critAt: THRESHOLDS.memory.crit,
          ...bandOf("memory", "memory", mem),
          live: liveHead,
          pulseKey,
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
          limit: THRESHOLDS.disk.warn,
          critAt: THRESHOLDS.disk.crit,
          ...bandOf("disk", "disk", disk),
          live: liveHead,
          pulseKey,
          detail: lm.disk_free ? `${gigabytes(lm.disk_free, 0)} livres` : undefined,
        },
        cpuTemp !== null
          ? {
              label: "Temperatura",
              term: "temperatura",
              value: cpuTemp.toFixed(0),
              unit: "°C",
              reading: temp,
              band: bandFor("cpuTemp"),
              historyMax: 100,
              limit: THRESHOLDS.cpuTemp.warn,
              critAt: THRESHOLDS.cpuTemp.crit,
            }
          : {
              label: "Memória virtual",
              term: "swap",
              value: lm.swap_percent?.toFixed(0) ?? "--",
              unit: "%",
              reading: swap,
              history: series("swap_percent"),
              historyMax: 100,
              limit: THRESHOLDS.swap.warn,
              critAt: THRESHOLDS.swap.crit,
              ...bandOf("swap", "swap", swap),
              live: liveHead,
              pulseKey,
              detail: lm.swap_total ? `de ${gigabytes(lm.swap_total, 0)}` : undefined,
            },
      ]
    : [];

  /*
   * Qual medida está puxando o estado geral. O veredito diz "sob pressão";
   * sem isto a pessoa precisa varrer os quatro canais para descobrir qual.
   * Só aponta quando há de fato um desvio — em estado normal não há o que
   * culpar, e a frase viraria ruído.
   */
  const driver = (() => {
    const worst = vitals.find((v) => v.reading.level === "crit") ?? vitals.find((v) => v.reading.level === "warn");
    if (!worst) return null;
    return { label: worst.label.toLowerCase(), value: `${worst.value}${worst.unit ?? ""}` };
  })();

  const avisosPanel = (
    <Panel className="flex flex-col gap-3 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-display text-md font-semibold text-fg">Avisos recentes</h3>
          <p className="mt-0.5 text-xs text-fg-3">
            {openAnomalies.length > 0
              ? pluralize(openAnomalies.length, "aviso em aberto", "avisos em aberto")
              : "Últimas 24 horas"}
          </p>
        </div>
        {machineAnomalies.length > 0 && <TextButton onClick={() => navigate("/anomalies")}>Ver todos</TextButton>}
      </div>
      {machineAnomalies.length === 0 ? (
        <p className="text-sm text-fg-2">
          Nenhum aviso nas últimas 24 horas.{" "}
          <span className="text-fg-3">
            {learning && (learning.learning ?? !learning.ml_ready)
              ? "A detecção ainda está aprendendo o normal deste computador."
              : "O sistema continua verificando."}
          </span>
        </p>
      ) : (
        <AnomalyTimeline>
          {machineAnomalies.slice(0, 6).map((a) => (
            <AnomalyEvent key={a.id} anomaly={a} onOpen={() => navigate(`/anomalies/${a.id}`)} />
          ))}
        </AnomalyTimeline>
      )}
    </Panel>
  );

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

      {/* A frota primeiro: qual computador precisa de mim agora. Só aparece
          com dois ou mais — com um, o painel abaixo já responde. */}
      <FleetOverview onSelect={setSelectedMachine} />

      <NextSteps />

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
        <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2">
          <p className="text-sm font-medium text-fg">{machine?.name}</p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {machine && <FocusModeControl machine={machine} onChange={poll.refresh} />}
            <FreshnessTag
              lastMetricAt={lm?.timestamp ?? machine?.last_seen}
              wsStatus={wsStatus}
              paused={machine ? !machine.is_active : false}
            />
          </div>
        </div>

        <Verdict
          level={overall}
          openAnomalies={openAnomalies}
          learning={learning}
          driver={driver}
          onOpenAnomaly={(id) => navigate(`/anomalies/${id}`)}
          onSeeAll={() => navigate("/anomalies")}
          actions={
            machine && lm ? (
              <>
                <DiagnoseButton
                  machineId={machine.id}
                  online={wsStatus === "open" || (!!lm && Date.now() - new Date(lm.timestamp).getTime() < 150000)}
                  variant="primary"
                />
                <Button variant="secondary" onClick={() => navigate(`/machines/${machine.id}`)}>
                  Ver análises deste computador
                </Button>
              </>
            ) : undefined
          }
        />

        {switching ? (
          <VitalsSkeleton />
        ) : (
          lm && (
            <div className="animate-fade">
              <VitalStrip items={vitals} />
            </div>
          )
        )}

        {/* Automação esperando uma decisão: fica no alto porque a janela de
            cancelamento é curta e vence sozinha. */}
        <PendingRuns />
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

      {lm && !switching && metrics.length > 1 ? (
        <div className="grid grid-cols-1 gap-4 min-[1081px]:grid-cols-3">
          <HistoryPanel
            metrics={metrics}
            lastTimestamp={lm.timestamp}
            now={now}
            className="min-[1081px]:col-span-2"
          />

          {avisosPanel}
        </div>
      ) : (
        avisosPanel
      )}

      {lm && !switching && (
        <details open className="group rounded-panel border border-hairline bg-surface">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 [&::-webkit-details-marker]:hidden">
            <h2 className="font-display text-md font-semibold text-fg">Detalhes do sistema</h2>
            <ChevronDown
              size={18}
              aria-hidden="true"
              className="flex-shrink-0 text-fg-3 transition-transform duration-200 ease-signal group-open:rotate-180"
            />
          </summary>
          <div className="grid grid-cols-1 divide-y divide-hairline border-t border-hairline md:grid-cols-3 md:divide-x md:divide-y-0">
              <div className="px-5 py-4">
                <PanelLabel className="mb-2">Sistema</PanelLabel>
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
                <PanelLabel className="mb-2">Rede e disco</PanelLabel>
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
                <PanelLabel className="mb-2">
                  {hasBattery ? "Bateria" : gpu ? "Placa de vídeo" : "Memória virtual"}
                </PanelLabel>
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
          </div>

          {/* GPU e bateria coexistem em notebook com placa dedicada: a terceira
              coluna mostra a bateria e a placa vem numa linha própria. */}
          {hasBattery && gpu && (
            <Panel tone="sunken" className="m-3 px-5 py-4">
              <PanelLabel className="mb-2">Placa de vídeo — {gpu.name}</PanelLabel>
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
            <Panel tone="sunken" className="m-3 px-5 py-4">
              <PanelLabel className="mb-2.5 flex items-center gap-1.5">
                Divisões do disco
                <Explain term="particoes" />
              </PanelLabel>
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
        </details>
      )}

      {machines.length > 1 && (
        <p className="text-xs text-fg-3">
          {pluralize(machines.length, "computador conectado", "computadores conectados")} ·{" "}
          <TextButton onClick={() => navigate("/machines")}>gerenciar</TextButton>
        </p>
      )}
    </div>
  );
}
