import type { Anomaly } from "../types";

export type MachineStatus = { open: number; worst: Anomaly | null };

const ORDEM: Record<string, number> = { low: 1, medium: 2, high: 3, critical: 4 };

/** Avisos em aberto agrupados por computador, com o mais grave de cada um. */
export function statusByMachine(openAnomalies: Anomaly[]): Record<number, MachineStatus> {
  const out: Record<number, MachineStatus> = {};
  for (const a of openAnomalies) {
    const st = (out[a.machine_id] ??= { open: 0, worst: null });
    st.open += 1;
    if (!st.worst || (ORDEM[a.severity] ?? 0) > (ORDEM[st.worst.severity] ?? 0)) st.worst = a;
  }
  return out;
}
