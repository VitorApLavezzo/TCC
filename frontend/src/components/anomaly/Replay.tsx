import { useEffect, useMemo, useRef, useState } from "react";
import { anomaliesApi, metricsApi } from "../../services/api";
import { Anomaly } from "../../types";
import { Skeleton } from "../ui/Skeleton";
import { bytesPerSec } from "../../lib/format";
import { Play, Pause, RotateCcw } from "lucide-react";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";

/**
 * Replay do incidente.
 *
 * Um gráfico é bom para ver que houve um pico; ele não mostra *quem* estava
 * consumindo a cada instante. Aqui a linha do tempo é percorrível: a cada
 * quadro, as barras mostram os programas daquele segundo, então dá para ver o
 * programa subir, dominar e (quando é o caso) sumir.
 *
 * A fonte preferida é a caixa-preta que o agente enviou (uma amostra a cada
 * 2 s, minutos antes do aviso). Sem ela, o replay usa as leituras normais de
 * 30 s em 30 s — mais grosso, mas a mesma leitura.
 */
interface Frame {
  t: number;
  label: string;
  cpu: number;
  mem: number;
  /** Rede e disco: o backend sempre mandou, a tela é que descartava. */
  connections?: number | null;
  netRecv?: number | null;
  netSent?: number | null;
  diskRead?: number | null;
  diskWrite?: number | null;
  processes: { name: string; cpu: number; mem: number }[];
}

type GaugeSpec = {
  key: keyof Frame;
  label: string;
  kind: "percent" | "bytes" | "count";
};

const CPU_MEM: GaugeSpec[] = [
  { key: "cpu", label: "Processador", kind: "percent" },
  { key: "mem", label: "Memória", kind: "percent" },
];
const REDE: GaugeSpec[] = [
  { key: "connections", label: "Conexões de rede", kind: "count" },
  { key: "netRecv", label: "Recebido", kind: "bytes" },
];
const DISCO: GaugeSpec[] = [
  { key: "diskRead", label: "Leitura de disco", kind: "bytes" },
  { key: "diskWrite", label: "Escrita de disco", kind: "bytes" },
];

/**
 * Quais medidores respondem à pergunta de cada aviso.
 *
 * Mostrar processador e memória num aviso de rede é a tela afirmando algo
 * sobre o que não foi medido — a mesma falha do cartão "e se eu fechar".
 * Os tipos ausentes daqui caem em processador e memória, que é o caso comum.
 */
const GAUGES_FOR: Record<string, GaugeSpec[]> = {
  network_spike: REDE,
  ddos_indicator: REDE,
  beaconing: REDE,
  disk_activity: DISCO,
  disk_full: DISCO,
  disk_forecast: DISCO,
  disk_space_change: DISCO,
};

export function Replay({ anomaly, blackboxId }: { anomaly: Anomaly; blackboxId?: number | null }) {
  const [frames, setFrames] = useState<Frame[] | null>(null);
  const [source, setSource] = useState<"caixa-preta" | "leituras">("leituras");
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;
    // A caixa-preta do agente só amostra processador e memória. Num aviso de
    // rede ou de disco ela é de alta resolução e não tem o dado que importa,
    // então as leituras normais valem mais: 30 s em vez de 2 s, mas medindo a
    // coisa certa. O rótulo da fonte continua dizendo qual está em uso.
    const needsWideMetrics = (GAUGES_FOR[anomaly.anomaly_type] ?? CPU_MEM) !== CPU_MEM;

    const load = async () => {
      if (blackboxId && !needsWideMetrics) {
        try {
          const res = await anomaliesApi.blackbox(blackboxId);
          const samples = res.data.samples ?? [];
          if (!cancelled && samples.length > 1) {
            setFrames(
              samples.map((s: any) => ({
                t: s.t * 1000,
                label: format(new Date(s.t * 1000), "HH:mm:ss", { locale: ptBR }),
                cpu: s.cpu ?? 0,
                mem: s.mem ?? 0,
                processes: (s.top ?? []).map((p: any) => ({ name: p.name, cpu: p.cpu ?? 0, mem: p.mem ?? 0 })),
              }))
            );
            setSource("caixa-preta");
            return;
          }
        } catch {
          /* cai para as leituras normais */
        }
      }
      try {
        const res = await metricsApi.window(anomaly.machine_id, anomaly.detected_at, 10);
        if (cancelled) return;
        const f = (res.data.frames ?? [])
          .filter((x: any) => x.t)
          .map((x: any) => ({
            t: new Date(x.t).getTime(),
            label: format(new Date(x.t), "HH:mm:ss", { locale: ptBR }),
            cpu: x.cpu ?? 0,
            mem: x.mem ?? 0,
            connections: x.connections,
            netRecv: x.net_recv,
            netSent: x.net_sent,
            diskRead: x.disk_read,
            diskWrite: x.disk_write,
            processes: (x.processes ?? []).map((p: any) => ({ name: p.name, cpu: p.cpu ?? 0, mem: p.mem ?? 0 })),
          }));
        setFrames(f);
        setSource("leituras");
      } catch {
        if (!cancelled) setFrames([]);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [anomaly.id, anomaly.machine_id, anomaly.detected_at, blackboxId]);

  // Começa no instante da detecção, não no início da janela
  useEffect(() => {
    if (!frames?.length) return;
    const target = new Date(anomaly.detected_at).getTime();
    let closest = 0;
    frames.forEach((f, i) => {
      if (Math.abs(f.t - target) < Math.abs(frames[closest].t - target)) closest = i;
    });
    setIndex(closest);
  }, [frames, anomaly.detected_at]);

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (!playing || !frames?.length) return;
    timerRef.current = setInterval(() => {
      setIndex((i) => {
        if (i >= frames.length - 1) {
          setPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, 350);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [playing, frames]);

  const detectionIndex = useMemo(() => {
    if (!frames?.length) return 0;
    const target = new Date(anomaly.detected_at).getTime();
    let closest = 0;
    frames.forEach((f, i) => {
      if (Math.abs(f.t - target) < Math.abs(frames[closest].t - target)) closest = i;
    });
    return closest;
  }, [frames, anomaly.detected_at]);

  if (frames === null) return <Skeleton className="h-40 w-full rounded-panel" />;
  if (frames.length < 2) return null;

  const frame = frames[Math.min(index, frames.length - 1)];
  const maxProc = Math.max(10, ...frame.processes.map((p) => p.cpu));
  const gauges = GAUGES_FOR[anomaly.anomaly_type] ?? CPU_MEM;
  // Rede e disco não têm teto natural como a porcentagem: a barra é relativa
  // ao maior valor da própria janela, senão ficaria sempre colada no zero.
  const maxOf = (key: keyof Frame) =>
    Math.max(1, ...frames.map((f) => Number(f[key] ?? 0)));

  return (
    <div className="rounded-panel border border-hairline bg-surface px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              if (index >= frames.length - 1) setIndex(0);
              setPlaying((p) => !p);
            }}
            aria-label={playing ? "Pausar" : "Reproduzir"}
            className="flex h-8 w-8 items-center justify-center rounded-control border border-edge text-fg-2 transition-colors hover:bg-raised hover:text-fg"
          >
            {playing ? <Pause size={13} aria-hidden="true" /> : <Play size={13} aria-hidden="true" />}
          </button>
          <button
            type="button"
            onClick={() => {
              setPlaying(false);
              setIndex(detectionIndex);
            }}
            aria-label="Voltar ao instante da detecção"
            className="flex h-8 w-8 items-center justify-center rounded-control text-fg-3 transition-colors hover:bg-raised hover:text-fg"
          >
            <RotateCcw size={13} aria-hidden="true" />
          </button>
          <span className="tnum font-mono text-sm text-fg">{frame.label}</span>
          {index === detectionIndex && <span className="channel-label text-accent">detecção</span>}
        </div>
        <span className="text-micro text-fg-3">
          {source === "caixa-preta" ? "caixa-preta · 1 quadro a cada 2 s" : "leituras · 1 quadro a cada 30 s"}
        </span>
      </div>

      {/* Linha do tempo com o marcador da detecção */}
      <div className="relative mt-3">
        <input
          type="range"
          min={0}
          max={frames.length - 1}
          value={index}
          onChange={(e) => {
            setPlaying(false);
            setIndex(Number(e.target.value));
          }}
          aria-label="Momento do replay"
          className="w-full accent-accent"
        />
        <span
          className="pointer-events-none absolute -top-1 h-2 w-px bg-accent"
          style={{ left: `${(detectionIndex / Math.max(frames.length - 1, 1)) * 100}%` }}
          aria-hidden="true"
        />
      </div>

      <div className="mt-3 flex gap-6">
        {gauges.map((g) => (
          <Gauge key={String(g.key)} spec={g} value={Number(frame[g.key] ?? 0)} max={maxOf(g.key)} />
        ))}
      </div>

      <div className="mt-4 space-y-1.5">
        <p className="channel-label">Quem estava consumindo processador</p>
        {frame.processes.length === 0 ? (
          <p className="text-xs text-fg-3">Sem detalhe de programas neste quadro.</p>
        ) : (
          frame.processes.slice(0, 5).map((p) => (
            <div key={p.name} className="flex items-center gap-3">
              <span className="w-36 flex-shrink-0 truncate font-mono text-xs text-fg-2" title={p.name}>
                {p.name}
              </span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-sunken">
                <div
                  className="h-full bg-fg-3 transition-[width] duration-300 ease-signal"
                  style={{ width: `${Math.min((p.cpu / maxProc) * 100, 100)}%` }}
                />
              </div>
              <span className="tnum w-12 flex-shrink-0 text-right font-mono text-xs text-fg">{p.cpu.toFixed(0)}%</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function Gauge({ spec, value, max }: { spec: GaugeSpec; value: number; max: number }) {
  // Rede e disco chegam do agente como TAXA (bytes por segundo, calculada
  // sobre o intervalo), não como total acumulado — o "/s" faz parte do
  // número e tirá-lo transformaria uma taxa em algo que ela não é.
  const texto = spec.kind === "bytes" ? bytesPerSec(value) : value.toFixed(0);
  const unidade = spec.kind === "percent" ? "%" : "";
  // Porcentagem tem teto de 100; contagem e bytes se medem contra a janela
  const preenchimento = spec.kind === "percent" ? Math.min(value, 100) : Math.min((value / max) * 100, 100);
  return (
    <div className="min-w-0 flex-1">
      <p className="channel-label">{spec.label}</p>
      <p className="tnum mt-0.5 font-mono text-readout-sm font-medium text-fg">
        {texto}
        {unidade && <span className="ml-0.5 text-md font-normal text-fg-3">{unidade}</span>}
      </p>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-sunken">
        <div
          className="h-full bg-fg-2 transition-[width] duration-300 ease-signal"
          style={{ width: `${preenchimento}%` }}
        />
      </div>
    </div>
  );
}
