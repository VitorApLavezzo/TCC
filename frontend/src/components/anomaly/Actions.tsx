import { useEffect, useRef, useState } from "react";
import { Anomaly, Machine, SECURITY_TYPES } from "../../types";
import { actionsApi, errorMessage } from "../../services/api";
import { processName } from "../../lib/format";
import { confirmBody, killParamsFor } from "../../lib/actions";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";
import { useConfirm } from "../ui/ConfirmDialog";

/** Ações de um clique: cada uma vira um comando que o agente executa; o painel acompanha até a resposta. */
export function AnomalyActions({ anomaly, machine }: { anomaly: Anomaly; machine?: Machine | null }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [pending, setPending] = useState<string | null>(null);
  const [watching, setWatching] = useState<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const track = (commandId: number, label: string) => {
    setWatching(commandId);
    pollRef.current = setInterval(async () => {
      try {
        const res = await actionsApi.command(commandId);
        if (res.data.status === "done" || res.data.status === "failed" || res.data.status === "expired") {
          if (pollRef.current) clearInterval(pollRef.current);
          setWatching(null);
          const msg = res.data.result?.message;
          if (res.data.status === "done") toast.success(`${label}: ${msg ?? "concluído"}`);
          else if (res.data.status === "expired")
            toast.error(`${label} não foi executado`, "O computador pode estar desligado ou offline.");
          else toast.error(`${label} falhou`, msg);
        }
      } catch {
        /* continua tentando */
      }
    }, 3000);
  };

  const run = async (command: string, label: string, params: Record<string, any> = {}, danger = false) => {
    if (danger) {
      const ok = await confirm({
        title: `${label}?`,
        body: confirmBody(command, machine?.name),
        confirmLabel: label,
        destructive: true,
      });
      if (!ok) return;
    }
    setPending(command);
    try {
      const res = await actionsApi.run(machine!.id, command, params, anomaly.id);
      toast.info(`${label} enviado ao computador…`);
      track(res.data.command_id, label);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setPending(null);
    }
  };

  if (!machine) return null;
  const isSecurity = SECURITY_TYPES.has(anomaly.anomaly_type);
  const isAdmin = (machine.system_info as any)?.is_admin;
  const proc = processName(anomaly);
  const beh = anomaly.affected_metrics?._behavior;
  const killParams = killParamsFor(proc, beh);
  const killLabel = killParams ? (proc ? `Encerrar ${proc}` : `Encerrar processo (PID ${killParams.pid})`) : null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {killLabel && killParams && (
        <Button
          size="sm"
          variant="secondary"
          loading={pending === "kill_process"}
          disabled={watching !== null}
          onClick={() => run("kill_process", killLabel, killParams, true)}
        >
          {killLabel}
        </Button>
      )}
      {(anomaly.anomaly_type === "disk_full" || anomaly.anomaly_type === "disk_forecast") && (
        <Button
          size="sm"
          variant="secondary"
          loading={pending === "clean_temp"}
          disabled={watching !== null}
          onClick={() => run("clean_temp", "Limpar temporários", {}, true)}
        >
          Limpar arquivos temporários
        </Button>
      )}
      {anomaly.anomaly_type === "network_spike" && (
        <Button size="sm" variant="secondary" loading={pending === "stop_sync_client"} disabled={watching !== null}
          onClick={() => run("stop_sync_client", "Pausar sincronização", {})}>
          Pausar sincronização de nuvem
        </Button>
      )}
      {isSecurity && !machine.network_isolated && (
        <Button
          size="sm"
          variant="danger"
          loading={pending === "isolate_network"}
          disabled={watching !== null || !isAdmin}
          title={isAdmin ? undefined : "O agente precisa de privilégios de administrador"}
          onClick={() => run("isolate_network", "Isolar da rede", {}, true)}
        >
          Isolar da rede
        </Button>
      )}
      {machine.network_isolated && (
        <Button size="sm" variant="secondary" loading={pending === "restore_network"} disabled={watching !== null}
          onClick={() => run("restore_network", "Restaurar a rede", {})}>
          Restaurar a rede
        </Button>
      )}
      {watching !== null && <span className="text-xs text-fg-3">executando no computador…</span>}
    </div>
  );
}
