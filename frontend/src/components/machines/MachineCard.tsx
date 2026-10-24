import { useEffect, useState } from "react";
import { useToast } from "../ui/Toast";
import { copyText, COPY_FAILED } from "../../lib/clipboard";
import { Link } from "react-router-dom";
import { Pause, Play, Trash2, ChevronDown, ChevronRight } from "lucide-react";
import { Anomaly, ANOMALY_TYPE_LABELS, Machine } from "../../types";
import { Button, IconButton } from "../ui/Button";
import { Severity } from "../ui/Badge";
import { StatusDot } from "../ui/Layout";
import { pluralize } from "../../lib/format";
import type { MachineStatus } from "../../lib/machineStatus";
import { Explain } from "../ui/Explain";
import { FreshnessTag } from "../FreshnessTag";
import { downloadInstaller, downloadUninstaller, serverOneLiner } from "../../utils/installers";

const INTERVAL_OPTIONS: { value: "auto" | "10" | "30" | "60"; label: string }[] = [
  { value: "auto", label: "Automática" },
  { value: "10", label: "Rápida (10 s)" },
  { value: "30", label: "Padrão (30 s)" },
  { value: "60", label: "Econômica (60 s)" },
];

function intervalLabel(value?: number | null): string {
  if (value === 10) return "Rápida (10 s)";
  if (value === 30) return "Padrão (30 s)";
  if (value === 60) return "Econômica (60 s)";
  return "Automática";
}

/**
 * A pergunta que a lista não respondia: este computador está bem? Antes só
 * dizia se ele estava conectado.
 */
function HealthLine({ machine, status }: { machine: Machine; status?: MachineStatus }) {
  if (!status || !machine.is_active) return null;
  if (status.open === 0) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-fg-2">
        <StatusDot tone="ok" />
        Nenhum aviso em aberto
      </span>
    );
  }
  const worst = status.worst!;
  return (
    <Link
      to={`/anomalies?computador=${machine.id}&abertos=1&periodo=720`}
      className="inline-flex min-w-0 items-center gap-2 text-xs text-fg-2 hover:text-fg"
    >
      <Severity severity={worst.severity} />
      <span className="truncate">
        {pluralize(status.open, "aviso em aberto", "avisos em aberto")} ·{" "}
        {(ANOMALY_TYPE_LABELS[worst.anomaly_type] ?? worst.anomaly_type).toLowerCase()}
      </span>
    </Link>
  );
}

/**
 * Uma máquina na lista.
 *
 * O conteúdo secundário — reinstalar, desinstalar — fica numa região expansível
 * separada por filete, não em caixas com borda e fundo próprios dentro do
 * cartão. A versão anterior tinha três níveis de caixa aninhada aqui.
 */
export function MachineCard({
  machine,
  onTogglePause,
  onDelete,
  onSetInterval,
  onSetRealtime,
  busy,
  status,
}: {
  machine: Machine;
  /** Avisos em aberto deste computador; ausente enquanto carrega. */
  status?: MachineStatus;
  onTogglePause: (m: Machine) => void;
  onDelete: (m: Machine) => void;
  onSetInterval: (m: Machine, value: 10 | 30 | 60 | null) => void;
  onSetRealtime: (m: Machine, minutes: number) => void;
  busy?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const toast = useToast();
  const [copied, setCopied] = useState<"token" | "cmd" | null>(null);
  // Só para forçar o recálculo da contagem regressiva do tempo real a cada segundo
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!machine.realtime_until) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, [machine.realtime_until]);

  const remainingMs = machine.realtime_until ? new Date(machine.realtime_until).getTime() - Date.now() : 0;
  const realtimeActive = remainingMs > 0;
  const remainingLabel = realtimeActive
    ? `${Math.floor(remainingMs / 60000)}:${String(Math.floor((remainingMs % 60000) / 1000)).padStart(2, "0")}`
    : null;

  const copy = async (what: "token" | "cmd") => {
    const ok = await copyText(
      what === "token" ? machine.agent_token : serverOneLiner({ token: machine.agent_token })
    );
    if (!ok) return toast.error(...COPY_FAILED);
    setCopied(what);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <li className="py-4">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          {/* Seta ao lado do nome: sem ela, nada dizia que o nome abre o
              histórico do computador. */}
          <Link
            to={`/machines/${machine.id}`}
            className="group inline-flex max-w-full items-center gap-1 text-sm font-medium text-fg hover:text-accent"
          >
            <span className="truncate">{machine.name}</span>
            <ChevronRight size={14} aria-hidden="true" className="flex-shrink-0 text-fg-3 group-hover:text-accent" />
          </Link>
          <p className="tnum mt-0.5 truncate font-mono text-xs text-fg-3">
            {machine.hostname}
            {machine.os_type ? ` · ${machine.os_type}` : ""}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5">
            <HealthLine machine={machine} status={status} />
            {/* wsStatus="idle": esta página não abre WebSocket, então o frescor
                vem do "visto por último". O horário exato fica no title. */}
            <FreshnessTag lastMetricAt={machine.last_seen} wsStatus="idle" paused={!machine.is_active} />
          </div>
          {realtimeActive && (
            <p className="tnum mt-2 flex flex-wrap items-center gap-x-2 text-xs text-fg-2">
              Tempo real ativo — restam {remainingLabel}, depois volta para {intervalLabel(machine.preferred_interval)}.
              <Button size="sm" variant="quiet" disabled={busy} onClick={() => onSetRealtime(machine, 0)}>
                Encerrar tempo real
              </Button>
            </p>
          )}
        </div>

        <div className="flex flex-shrink-0 items-center gap-1">
          <Button
            size="sm"
            variant="quiet"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            icon={
              <ChevronDown
                size={12}
                aria-hidden="true"
                className={`transition-transform ${open ? "rotate-180" : ""}`}
              />
            }
          >
            Configurações
          </Button>
          <IconButton
            label={machine.is_active ? `Pausar a coleta de ${machine.name}` : `Retomar a coleta de ${machine.name}`}
            disabled={busy}
            icon={machine.is_active ? <Pause size={13} aria-hidden="true" /> : <Play size={13} aria-hidden="true" />}
            onClick={() => onTogglePause(machine)}
          />
          <IconButton
            label={`Remover ${machine.name} do painel`}
            tone="danger"
            disabled={busy}
            icon={<Trash2 size={13} aria-hidden="true" />}
            onClick={() => onDelete(machine)}
          />
        </div>
      </div>

      {!machine.is_active && (
        <p className="mt-2 text-xs leading-relaxed text-warn">
          A coleta está pausada — nenhum problema será detectado neste computador até você retomar. O agente segue
          instalado e mantendo contato.
        </p>
      )}

      {/* Frequência de leitura e tempo real ficavam à mostra em toda linha:
          ajuste fino que quase ninguém usa, disputando espaço com o que
          importa — se o computador está bem. */}
      {open && (
        <div className="mt-3 space-y-4 border-t border-hairline pt-3">
          <div>
            <p className="text-xs font-medium text-fg-2">Leituras</p>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
              <span className="inline-flex items-center gap-1.5">
                <label htmlFor={`interval-${machine.id}`} className="text-xs text-fg-3">
                  Frequência de leitura
                </label>
                <select
                  id={`interval-${machine.id}`}
                  value={machine.preferred_interval ? String(machine.preferred_interval) : "auto"}
                  disabled={busy}
                  onChange={(e) =>
                    onSetInterval(machine, e.target.value === "auto" ? null : (Number(e.target.value) as 10 | 30 | 60))
                  }
                  className="h-8 rounded-control border border-edge bg-surface px-2 text-xs text-fg focus:border-accent disabled:opacity-45"
                >
                  {INTERVAL_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <Explain term="frequencia_leitura" />
              </span>
              {!realtimeActive && (
                <span className="inline-flex items-center gap-1.5">
                  <Button size="sm" variant="secondary" disabled={busy} onClick={() => onSetRealtime(machine, 30)}>
                    Tempo real por 30 min
                  </Button>
                  <Explain term="tempo_real" />
                </span>
              )}
              {/* Sem leitura ainda, o intervalo é desconhecido — melhor não
                  dizer nada do que mostrar um "?" no lugar do número. */}
              {machine.collection_interval != null && (
                <span className="tnum text-xs text-fg-3">Lendo a cada {machine.collection_interval} s agora</span>
              )}
            </div>
          </div>

          <div>
            <p className="text-xs font-medium text-fg-2">Reinstalar o agente</p>
            <p className="mt-1 max-w-prose text-xs leading-relaxed text-fg-3">
              Estes instaladores já trazem a identificação deste computador embutida — sem código e sem prazo de validade.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={() => downloadInstaller("windows", { token: machine.agent_token })}>
                Baixar para Windows
              </Button>
              <Button size="sm" onClick={() => downloadInstaller("linux", { token: machine.agent_token })}>
                Baixar para Linux
              </Button>
              <Button size="sm" variant="quiet" onClick={() => copy("cmd")}>
                {copied === "cmd" ? "Comando copiado" : "Copiar comando p/ servidor"}
              </Button>
              <span className="inline-flex items-center gap-1.5">
                <Button size="sm" variant="quiet" onClick={() => copy("token")}>
                  {copied === "token" ? "Identificação copiada" : "Copiar identificação"}
                </Button>
                <Explain term="agent_token" />
              </span>
            </div>
          </div>

          <div>
            <p className="text-xs font-medium text-fg-2">Parar de monitorar</p>
            <ol className="mt-1.5 max-w-prose space-y-1.5 text-xs leading-relaxed text-fg-3">
              <li>1. Baixe o desinstalador do sistema correspondente.</li>
              <li>
                2. Execute o arquivo <span className="text-fg-2">no computador monitorado</span> — dois cliques no
                Windows; no Linux, <code className="font-mono text-fg-2">bash remover-anomalydetect.sh</code>.
              </li>
              <li>
                3. Ele encerra o agente, apaga os arquivos, e o computador sai desta lista sozinho junto com o histórico.
              </li>
            </ol>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" variant="danger" onClick={() => downloadUninstaller("windows", machine.agent_token)}>
                Desinstalador Windows
              </Button>
              <Button size="sm" variant="danger" onClick={() => downloadUninstaller("linux", machine.agent_token)}>
                Desinstalador Linux
              </Button>
            </div>
            <p className="mt-2 max-w-prose text-xs leading-relaxed text-fg-3">
              A lixeira acima remove só do painel — o agente segue instalado e será desativado por não conseguir mais
              se conectar. Para limpeza completa, prefira o desinstalador.
            </p>
          </div>
        </div>
      )}
    </li>
  );
}
