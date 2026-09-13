/** Formatadores compartilhados — antes estavam duplicados dentro das páginas. */

export function bytesPerSec(val?: number | null) {
  if (!val) return "0 B/s";
  if (val < 1024) return `${val.toFixed(0)} B/s`;
  if (val < 1024 * 1024) return `${(val / 1024).toFixed(1)} KB/s`;
  return `${(val / 1024 / 1024).toFixed(1)} MB/s`;
}

export function gigabytes(bytes?: number | null, digits = 1) {
  if (bytes === null || bytes === undefined) return "--";
  return `${(bytes / 1024 ** 3).toFixed(digits)} GB`;
}

export function formatUptime(seconds?: number | null) {
  if (!seconds) return "--";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

/**
 * "há 12s", "há 4min", "há 2h". Curto de propósito: aparece ao lado do nome
 * da máquina e precisa caber sem quebrar a linha.
 */
export function timeAgo(iso?: string | Date | null, now: number = Date.now()) {
  if (!iso) return null;
  const then = typeof iso === "string" ? new Date(iso).getTime() : iso.getTime();
  if (Number.isNaN(then)) return null;
  const secs = Math.max(0, Math.round((now - then) / 1000));
  if (secs < 10) return "agora";
  if (secs < 60) return `há ${secs}s`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `há ${mins}min`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `há ${hours}h`;
  const days = Math.round(hours / 24);
  return `há ${days}d`;
}

/** Contagem com plural correto: pluralize(1, "máquina") → "1 máquina". */
export function pluralize(n: number, singular: string, plural = `${singular}s`) {
  return `${n} ${n === 1 ? singular : plural}`;
}

/**
 * Nome do programa responsável, ou null quando não dá pra identificar.
 * Avisos antigos (e agentes desatualizados) gravaram "?" como nome — isso
 * nunca deve aparecer na interface como se fosse um nome de verdade.
 */
export function processName(anomaly?: { responsible_process?: string | null } | null): string | null {
  const raw = anomaly?.responsible_process;
  if (!raw) return null;
  const trimmed = raw.trim();
  return trimmed && trimmed !== "?" ? trimmed : null;
}
