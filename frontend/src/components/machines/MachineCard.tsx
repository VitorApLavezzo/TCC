import { useState } from "react";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Pause, Play, Trash2, ChevronDown } from "lucide-react";
import { Machine } from "../../types";
import { Button, IconButton } from "../ui/Button";
import { Explain } from "../ui/Explain";
import { FreshnessTag } from "../FreshnessTag";
import { downloadInstaller, downloadUninstaller, serverOneLiner } from "../../utils/installers";

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
  busy,
}: {
  machine: Machine;
  onTogglePause: (m: Machine) => void;
  onDelete: (m: Machine) => void;
  busy?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState<"token" | "cmd" | null>(null);

  const copy = async (what: "token" | "cmd") => {
    await navigator.clipboard.writeText(
      what === "token" ? machine.agent_token : serverOneLiner({ token: machine.agent_token })
    );
    setCopied(what);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <li className="py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-fg">{machine.name}</p>
          <p className="tnum mt-0.5 truncate font-mono text-xs text-fg-3">
            {machine.hostname}
            {machine.os_type ? ` · ${machine.os_type}` : ""}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
            {/* wsStatus="idle": esta página não abre WebSocket, então o frescor
                vem do "visto por último", que é o dado disponível aqui. */}
            <FreshnessTag lastMetricAt={machine.last_seen} wsStatus="idle" paused={!machine.is_active} />
            {machine.last_seen && (
              <span className="tnum text-micro text-fg-3">
                último contato {format(new Date(machine.last_seen), "dd/MM HH:mm:ss", { locale: ptBR })}
              </span>
            )}
          </div>
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
            Instalação
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

      {open && (
        <div className="mt-3 space-y-4 border-t border-hairline pt-3">
          <div>
            <p className="text-xs font-medium text-fg-2">Reinstalar o agente</p>
            <p className="mt-1 max-w-prose text-xs leading-relaxed text-fg-3">
              Estes instaladores já trazem a identificação desta máquina embutida — sem código e sem prazo de validade.
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
                3. Ele encerra o agente, apaga os arquivos, e a máquina sai desta lista sozinha junto com o histórico.
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
