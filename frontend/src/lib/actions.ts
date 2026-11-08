import { SECURITY_TYPES } from "../types";
import { pluralize, processName } from "./format";

/**
 * O que cada ação remota faz de fato, para a confirmação não prometer mais
 * do que o sistema entrega.
 */
const CONSEQUENCES: Record<string, string> = {
  kill_process: "O programa fecha na hora, e o que estiver aberto nele sem salvar se perde.",
  clean_temp: "Os arquivos temporários são apagados e não voltam. Programas abertos podem precisar ser reabertos.",
  isolate_network:
    "O computador fica sem internet e sem rede até você clicar em “Restaurar a rede” neste mesmo aviso.",
};

export function confirmBody(command: string, machineName?: string | null) {
  const where = machineName ? `em ${machineName}` : "no computador";
  const consequence = CONSEQUENCES[command] ?? "";
  return `Esta ação será executada ${where}. ${consequence}`.trim();
}

/**
 * Parâmetros de "encerrar processo": vai a identidade da instância (pid, caminho
 * e hora de início) para o agente conferir. Sem pid não há botão: só pelo nome,
 * o agente encerraria todo processo homônimo (os svchost.exe verdadeiros, inclusive).
 */
export function killParamsFor(
  proc: string | null | undefined,
  beh: { pid?: number; exe?: string; create_time?: number } | null | undefined,
) {
  if (!beh?.pid) return null;
  return {
    pid: beh.pid,
    ...(proc ? { name: proc } : {}),
    ...(beh.exe ? { exe: beh.exe } : {}),
    ...(beh.create_time != null ? { create_time: beh.create_time } : {}),
  };
}

export function bulkResolveMessage(count: number, reopen: boolean) {
  const done = reopen ? "reaberto" : "resolvido";
  return `${pluralize(count, "aviso", "avisos")} ${count === 1 ? done : `${done}s`}.`;
}

// Mesmas condições dos botões de components/anomaly/Actions.tsx: sem nenhum, a seção não aparece vazia
export function hasAnomalyActions(
  anomaly: { anomaly_type: string; responsible_process?: string | null; affected_metrics?: any },
  machine: { network_isolated?: boolean } | null | undefined,
) {
  if (!machine) return false;
  return (
    !!killParamsFor(processName(anomaly), anomaly.affected_metrics?._behavior) ||
    ["disk_full", "disk_forecast", "network_spike"].includes(anomaly.anomaly_type) ||
    SECURITY_TYPES.has(anomaly.anomaly_type) ||
    !!machine.network_isolated
  );
}
