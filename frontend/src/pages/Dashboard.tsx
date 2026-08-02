import { useState, useCallback, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { anomaliesApi, metricsApi, machinesApi } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { useWebSocket } from "../hooks/useWebSocket";
import { Machine, Metric, Anomaly, AnomalyStats, ANOMALY_TYPE_LABELS } from "../types";
import { StatCard } from "../components/ui/StatCard";
import { MetricChart } from "../components/charts/MetricChart";
import { SeverityBadge } from "../components/ui/Badge";
import { Card } from "../components/ui/Card";
import { format, formatDistanceToNow } from "date-fns";
import { ptBR } from "date-fns/locale";
import {
  Cpu, AlertTriangle, Monitor, CheckCircle2, Clock,
  Activity, Wifi, Thermometer, Battery, BatteryCharging,
  HardDrive, MemoryStick,
} from "lucide-react";

const MAX_CHART_POINTS = 60;

function bytesPerSec(val?: number) {
  if (!val) return "0 B/s";
  if (val < 1024) return `${val.toFixed(0)} B/s`;
  if (val < 1024 * 1024) return `${(val / 1024).toFixed(1)} KB/s`;
  return `${(val / 1024 / 1024).toFixed(1)} MB/s`;
}

function formatUptime(seconds?: number) {
  if (!seconds) return "--";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export function Dashboard() {
  const navigate = useNavigate();
  const [machines, setMachines] = useState<Machine[]>([]);
  const [selectedMachine, setSelectedMachine] = useState<number | null>(null);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [latestMetric, setLatestMetric] = useState<Metric | null>(null);
  const [anomalies, setAnomalies] = useState<Anomaly[]>([]);
  const [stats, setStats] = useState<AnomalyStats | null>(null);
  const [isLive, setIsLive] = useState(false);
  const selectedRef = useRef<number | null>(null);
  selectedRef.current = selectedMachine;

  const fetchAll = useCallback(async () => {
    const [machRes, anomRes, statsRes] = await Promise.all([
      machinesApi.list(),
      anomaliesApi.list({ hours: 24 }),
      anomaliesApi.stats(24),
    ]);
    const machineList: Machine[] = machRes.data;
    setMachines(machineList);
    setAnomalies(anomRes.data);
    setStats(statsRes.data);

    const firstActive = selectedRef.current ?? machineList.find((m) => m.is_active)?.id ?? null;
    if (!selectedRef.current && firstActive) setSelectedMachine(firstActive);

    const mid = selectedRef.current ?? firstActive;
    if (mid) {
      const [mRes, lRes] = await Promise.all([
        metricsApi.list(mid, 3),
        metricsApi.latest(mid).catch(() => ({ data: null })),
      ]);
      setMetrics(mRes.data);
      setLatestMetric(lRes.data);
    }
  }, []);

  usePolling(fetchAll, 60000);

  // Troca de máquina: limpa os dados da anterior e busca os da nova imediatamente
  // (sem isso, o dashboard ficava até 60s mostrando a máquina antiga)
  useEffect(() => {
    if (!selectedMachine) return;
    setMetrics([]);
    setLatestMetric(null);
    setIsLive(false);
    Promise.all([
      metricsApi.list(selectedMachine, 3),
      metricsApi.latest(selectedMachine).catch(() => ({ data: null })),
    ]).then(([mRes, lRes]) => {
      setMetrics(mRes.data.slice(-MAX_CHART_POINTS));
      setLatestMetric(lRes.data);
    });
  }, [selectedMachine]);

  useWebSocket(selectedMachine ? `/ws/machine/${selectedMachine}` : null, (msg) => {
    if (msg.type === "metric") {
      const m = msg.data as Metric;
      setLatestMetric(m);
      setMetrics((prev) => [...prev, m].slice(-MAX_CHART_POINTS));
      setIsLive(true);
    }
    if (msg.type === "anomaly") {
      Promise.all([anomaliesApi.list({ hours: 24 }), anomaliesApi.stats(24)]).then(
        ([a, s]) => { setAnomalies(a.data); setStats(s.data); }
      );
    }
  });

  const lm = latestMetric;
  const gpu = lm?.gpu_metrics?.[0];
  const hasBattery = lm?.battery_percent !== null && lm?.battery_percent !== undefined;

  const cpuTemp = (() => {
    if (!lm?.temperatures) return null;
    const t = lm.temperatures as Record<string, any[]>;
    const entries = Object.values(t).flat();
    const entry = entries.find((e: any) => e.current > 0);
    return entry ? (entry as any).current : null;
  })();

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Dashboard</h1>
          <p className="text-gray-400 text-sm mt-0.5">Monitoramento em tempo real</p>
        </div>
        {isLive && (
          <div className="flex items-center gap-2 text-xs text-green-400 bg-green-400/10 border border-green-400/20 px-3 py-1.5 rounded-full">
            <Wifi size={12} className="animate-pulse" />
            AO VIVO
          </div>
        )}
      </div>

      {/* Stats topo */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard title="Máquinas Ativas" value={machines.filter(m => m.is_active).length}
          subtitle={`${machines.length} registradas`} icon={<Monitor size={18} />} color="blue" />
        <StatCard title="Anomalias (24h)" value={stats?.total ?? 0}
          subtitle={`${stats?.unresolved ?? 0} não resolvidas`} icon={<AlertTriangle size={18} />}
          color={(stats?.unresolved ?? 0) > 0 ? "red" : "green"} />
        <StatCard title="Uptime" value={formatUptime(lm?.uptime_seconds)}
          subtitle={lm ? `${lm.process_count} processos` : "aguardando dados"}
          icon={<Activity size={18} />} color="purple" />
        <StatCard title="Load Avg" value={lm?.load_avg_1?.toFixed(2) ?? "--"}
          subtitle={`5m: ${lm?.load_avg_5?.toFixed(2) ?? "--"} · 15m: ${lm?.load_avg_15?.toFixed(2) ?? "--"}`}
          icon={<Cpu size={18} />} color="blue" />
      </div>

      {/* Seletor de máquina */}
      {machines.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {machines.map((m) => (
            <button key={m.id} onClick={() => setSelectedMachine(m.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors border ${
                selectedMachine === m.id
                  ? "bg-blue-600/20 text-blue-400 border-blue-600/40"
                  : "text-gray-400 border-gray-700 hover:border-gray-600"
              }`}>
              <Monitor size={12} className="inline mr-1.5" />{m.name}
            </button>
          ))}
        </div>
      )}

      {/* Métricas ao vivo */}
      {lm && (
        <>
          {/* Linha 1: CPU, Mem, Disco, Swap */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              { label: "CPU", value: lm.cpu_percent, color: "text-blue-400", sub: lm.cpu_freq_current ? `${(lm.cpu_freq_current/1000).toFixed(2)} GHz` : undefined },
              { label: "Memória", value: lm.mem_percent, color: "text-purple-400", sub: lm.mem_total ? `${((lm.mem_used||0)/1024**3).toFixed(1)} / ${(lm.mem_total/1024**3).toFixed(1)} GB` : undefined },
              { label: "Disco", value: lm.disk_percent, color: "text-yellow-400", sub: lm.disk_free ? `${(lm.disk_free/1024**3).toFixed(1)} GB livres` : undefined },
              { label: "Swap", value: lm.swap_percent, color: "text-orange-400", sub: lm.swap_total ? `${(lm.swap_total/1024**3).toFixed(1)} GB total` : undefined },
            ].map(({ label, value, color, sub }) => (
              <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-4 text-center">
                <p className="text-xs text-gray-500 mb-1">{label}</p>
                <p className={`text-3xl font-bold ${color}`}>{value?.toFixed(0) ?? "--"}<span className="text-lg">%</span></p>
                {sub && <p className="text-xs text-gray-600 mt-1">{sub}</p>}
              </div>
            ))}
          </div>

          {/* Linha 2: GPU */}
          {gpu && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <div className="w-2 h-2 rounded-full bg-green-400" />
                <h3 className="text-xs font-medium text-gray-400 uppercase tracking-wider">GPU — {gpu.name}</h3>
                {gpu.driver && <span className="text-xs text-gray-600 ml-auto">Driver {gpu.driver}</span>}
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <div className="text-center">
                  <p className="text-xs text-gray-500">Uso</p>
                  <p className="text-2xl font-bold text-green-400">{gpu.load_percent?.toFixed(0) ?? "--"}<span className="text-sm">%</span></p>
                </div>
                <div className="text-center">
                  <p className="text-xs text-gray-500">VRAM</p>
                  <p className="text-2xl font-bold text-teal-400">{gpu.mem_percent?.toFixed(0) ?? "--"}<span className="text-sm">%</span></p>
                  {gpu.mem_total_mb && <p className="text-xs text-gray-600">{gpu.mem_used_mb?.toFixed(0)}/{gpu.mem_total_mb?.toFixed(0)} MB</p>}
                </div>
                <div className="text-center">
                  <p className="text-xs text-gray-500">Temperatura</p>
                  <p className={`text-2xl font-bold ${(gpu.temperature||0) > 80 ? "text-red-400" : "text-orange-400"}`}>
                    {gpu.temperature?.toFixed(0) ?? "--"}<span className="text-sm">°C</span>
                  </p>
                </div>
                <div className="text-center">
                  <p className="text-xs text-gray-500">VRAM Total</p>
                  <p className="text-2xl font-bold text-gray-300">{gpu.mem_total_mb ? `${(gpu.mem_total_mb/1024).toFixed(1)}` : "--"}<span className="text-sm"> GB</span></p>
                </div>
              </div>
            </div>
          )}

          {/* Linha 3: Rede, Temperatura CPU, Bateria */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Rede</p>
              <div className="space-y-1.5">
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">↑ Upload</span>
                  <span className="text-green-400 font-mono">{bytesPerSec(lm.net_bytes_sent)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">↓ Download</span>
                  <span className="text-blue-400 font-mono">{bytesPerSec(lm.net_bytes_recv)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Conexões</span>
                  <span className="text-white font-mono">{lm.net_connections}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Disco Leitura</span>
                  <span className="text-yellow-400 font-mono">{bytesPerSec(lm.disk_read_bytes)}</span>
                </div>
                <div className="flex justify-between text-sm">
                  <span className="text-gray-400">Disco Escrita</span>
                  <span className="text-orange-400 font-mono">{bytesPerSec(lm.disk_write_bytes)}</span>
                </div>
              </div>
            </div>

            {cpuTemp && (
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Thermometer size={14} className="text-orange-400" />
                  <p className="text-xs text-gray-500 uppercase tracking-wider">Temperatura</p>
                </div>
                <p className={`text-4xl font-bold mt-2 ${cpuTemp > 85 ? "text-red-400" : cpuTemp > 70 ? "text-orange-400" : "text-green-400"}`}>
                  {cpuTemp.toFixed(0)}°C
                </p>
                <p className="text-xs text-gray-600 mt-1">
                  {cpuTemp > 85 ? "Temperatura crítica!" : cpuTemp > 70 ? "Temperatura elevada" : "Normal"}
                </p>
              </div>
            )}

            {hasBattery && (
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  {lm.battery_plugged
                    ? <BatteryCharging size={14} className="text-green-400" />
                    : <Battery size={14} className="text-yellow-400" />}
                  <p className="text-xs text-gray-500 uppercase tracking-wider">Bateria</p>
                </div>
                <p className={`text-4xl font-bold mt-2 ${(lm.battery_percent||0) < 20 ? "text-red-400" : (lm.battery_percent||0) < 50 ? "text-yellow-400" : "text-green-400"}`}>
                  {lm.battery_percent?.toFixed(0)}%
                </p>
                <p className="text-xs text-gray-600 mt-1">
                  {lm.battery_plugged ? "Carregando" : lm.battery_secs_left
                    ? `~${Math.floor((lm.battery_secs_left||0)/3600)}h${Math.floor(((lm.battery_secs_left||0)%3600)/60)}m restantes`
                    : "Descarregando"}
                </p>
                {lm.battery_health_percent != null && (
                  <div className="mt-3 pt-3 border-t border-gray-800">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-500">Saúde da bateria</span>
                      <span className={`text-sm font-semibold ${
                        lm.battery_health_percent >= 80 ? "text-green-400"
                        : lm.battery_health_percent >= 50 ? "text-yellow-400"
                        : "text-red-400"
                      }`}>
                        {lm.battery_health_percent.toFixed(0)}%
                        {" · "}
                        {lm.battery_health_percent >= 80 ? "Boa" : lm.battery_health_percent >= 50 ? "Regular" : "Considere trocar"}
                      </span>
                    </div>
                    <div className="w-full bg-gray-800 rounded-full h-1.5 mt-1.5">
                      <div
                        className={`h-1.5 rounded-full ${
                          lm.battery_health_percent >= 80 ? "bg-green-500"
                          : lm.battery_health_percent >= 50 ? "bg-yellow-500"
                          : "bg-red-500"
                        }`}
                        style={{ width: `${Math.min(lm.battery_health_percent, 100)}%` }}
                      />
                    </div>
                    {lm.battery_cycle_count != null && (
                      <p className="text-xs text-gray-600 mt-1.5">{lm.battery_cycle_count} ciclos de carga</p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Partições de disco */}
          {lm.disk_partitions && lm.disk_partitions.length > 1 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="flex items-center gap-2 mb-3">
                <HardDrive size={14} className="text-gray-400" />
                <p className="text-xs text-gray-500 uppercase tracking-wider">Partições de Disco</p>
              </div>
              <div className="space-y-2">
                {lm.disk_partitions.map((p) => (
                  <div key={p.mountpoint} className="flex items-center gap-3">
                    <span className="text-xs text-gray-400 w-24 truncate font-mono">{p.mountpoint}</span>
                    <div className="flex-1 bg-gray-800 rounded-full h-2">
                      <div
                        className={`h-2 rounded-full ${p.percent > 90 ? "bg-red-500" : p.percent > 70 ? "bg-yellow-500" : "bg-blue-500"}`}
                        style={{ width: `${p.percent}%` }}
                      />
                    </div>
                    <span className="text-xs text-gray-400 w-12 text-right">{p.percent}%</span>
                    <span className="text-xs text-gray-600 w-24 text-right">{p.free_gb.toFixed(1)} GB livres</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Gráficos */}
      {metrics.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <MetricChart metrics={metrics} dataKey="cpu_percent" color="#3b82f6" label="CPU %" />
          <MetricChart metrics={metrics} dataKey="mem_percent" color="#8b5cf6" label="Memória %" />
          <MetricChart metrics={metrics} dataKey="disk_percent" color="#f59e0b" label="Disco %" />
          <MetricChart metrics={metrics} dataKey="swap_percent" color="#f97316" label="Swap %" />
          <MetricChart metrics={metrics} dataKey="net_connections" color="#10b981" label="Conexões de Rede"
            unit=" conn" domain={[0, Math.max(...metrics.map((m) => m.net_connections ?? 0)) + 10]} />
          {metrics.some(m => m.gpu_metrics && m.gpu_metrics.length > 0) && (
            <MetricChart
              metrics={metrics.map(m => ({ ...m, gpu_load: m.gpu_metrics?.[0]?.load_percent ?? 0 } as any))}
              dataKey={"gpu_load" as any}
              color="#22d3ee"
              label="GPU %"
            />
          )}
        </div>
      )}

      {machines.length === 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-12 text-center">
          <Monitor size={40} className="text-gray-600 mx-auto mb-3" />
          <p className="text-gray-300 font-medium">Nenhuma máquina registrada</p>
          <button onClick={() => navigate("/machines")}
            className="mt-4 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors">
            Adicionar Máquina
          </button>
        </div>
      )}

      {/* Anomalias recentes */}
      {anomalies.length > 0 && (
        <div>
          <h2 className="text-base font-semibold text-white mb-3">Anomalias Recentes (24h)</h2>
          <div className="space-y-2">
            {anomalies.slice(0, 8).map((a) => (
              <Card key={a.id} onClick={() => navigate(`/anomalies/${a.id}`)} className="flex items-center gap-4">
                <div className="flex-shrink-0">
                  {a.is_resolved
                    ? <CheckCircle2 size={18} className="text-green-400" />
                    : <AlertTriangle size={18} className="text-orange-400" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-white text-sm font-medium">{ANOMALY_TYPE_LABELS[a.anomaly_type] || a.anomaly_type}</span>
                    <SeverityBadge severity={a.severity} />
                  </div>
                  {a.explanation?.summary && (
                    <p className="text-gray-400 text-xs mt-0.5 truncate">{a.explanation.summary}</p>
                  )}
                </div>
                <div className="flex-shrink-0 text-xs text-gray-500 flex items-center gap-1">
                  <Clock size={11} />
                  {format(new Date(a.detected_at), "dd/MM HH:mm", { locale: ptBR })}
                </div>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
