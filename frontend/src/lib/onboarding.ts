import { LanguageLevel } from "../types";

export type Severity = "low" | "medium" | "high" | "critical";

const SEVERITY_ORDER: Record<Severity, number> = { low: 1, medium: 2, high: 3, critical: 4 };

export interface QuietHours {
  enabled: boolean;
  from: number;
  to: number;
}

export interface NotificationChoices {
  min_severity: Severity;
  quiet_hours: QuietHours;
  persist_minutes: number;
  digest: { enabled: boolean; hour?: number };
  critical_bypasses_quiet?: boolean;
  channels?: { email?: boolean; telegram?: boolean };
}

export interface SampleAlert {
  hour: number;
  minute: number;
  severity: Severity;
  title: string;
  /** Some sozinho em poucos minutos, como um pico de processador. */
  fadesQuickly: boolean;
}

export type Outcome =
  | { kind: "now" }
  | { kind: "later"; at: number }
  | { kind: "digest" }
  | { kind: "panel" }
  | { kind: "settled" };

/** Mesma regra de `notifications._in_quiet_hours` no backend. */
export function inQuietHours(hour: number, quiet: QuietHours): boolean {
  if (!quiet.enabled) return false;
  const start = Math.max(0, Math.min(quiet.from, 23));
  const rawEnd = Math.max(0, Math.min(quiet.to, 24));
  if (start === 0 && rawEnd === 24) return true;
  const end = rawEnd % 24;
  if (start === end) return false;
  return start < end ? start <= hour && hour < end : hour >= start || hour < end;
}

/** O que o backend faria com este aviso, na ordem de `notifications.on_anomaly`. */
export function outcomeFor(alert: SampleAlert, prefs: NotificationChoices): Outcome {
  if (SEVERITY_ORDER[alert.severity] < SEVERITY_ORDER[prefs.min_severity]) {
    return prefs.digest.enabled ? { kind: "digest" } : { kind: "panel" };
  }
  if (prefs.persist_minutes > 0 && alert.fadesQuickly) return { kind: "settled" };
  const bypass = alert.severity === "critical" && prefs.critical_bypasses_quiet !== false;
  if (inQuietHours(alert.hour, prefs.quiet_hours) && !bypass) {
    return { kind: "later", at: prefs.quiet_hours.to % 24 };
  }
  return { kind: "now" };
}

export const SAMPLE_DAY: SampleAlert[] = [
  { hour: 2, minute: 40, severity: "medium", title: "Memória subindo sem parar", fadesQuickly: false },
  { hour: 9, minute: 15, severity: "low", title: "Pico rápido de processador", fadesQuickly: true },
  { hour: 11, minute: 30, severity: "medium", title: "Programa desconhecido usando a rede", fadesQuickly: true },
  { hour: 14, minute: 5, severity: "high", title: "Processador travado em 100%", fadesQuickly: false },
  { hour: 16, minute: 50, severity: "low", title: "Disco mais lento que o normal", fadesQuickly: false },
  { hour: 20, minute: 20, severity: "high", title: "Temperatura acima do normal", fadesQuickly: false },
  { hour: 23, minute: 45, severity: "critical", title: "Arquivos-isca alterados", fadesQuickly: false },
];

/** O mesmo aviso escrito nos três níveis, para a pessoa escolher vendo. */
export const LEVEL_SAMPLES: Record<LanguageLevel, { what: string; todo: string }> = {
  leigo: {
    what: "O Chrome está ocupando cada vez mais memória e não devolve. Se continuar assim, o computador vai ficar lento.",
    todo: "Feche as abas que você não está usando ou feche e abra o Chrome de novo.",
  },
  intermediario: {
    what: "O uso de RAM do Chrome subiu de 1,2 GB para 3,8 GB em duas horas, sem cair. Parece um vazamento de memória.",
    todo: "Aperte Shift+Esc no Chrome para ver as abas mais pesadas e feche-as, ou reinicie o navegador.",
  },
  tecnico: {
    what: "chrome.exe: memória residente de 1,2 para 3,8 GB em 2 h (+1,3 GB/h), sem retração. Compatível com memory leak, 3,1σ acima da linha de base da máquina.",
    todo: "Inspecione os processos renderer no Gerenciador de tarefas do Chrome e reinicie o processo responsável.",
  },
};
