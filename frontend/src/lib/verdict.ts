import { Level, worstLevel } from "./health";

/**
 * O estado que o selo do veredito mostra: o pior entre a leitura do momento e
 * os avisos em aberto. Aviso crítico conta como crítico; qualquer outro aviso
 * em aberto, como atenção.
 */
export function verdictTone(level: Level, openAnomalies: { severity: string }[]): Level {
  if (!openAnomalies.length) return level;
  const fromAnomalies: Level = openAnomalies.some((a) => a.severity === "critical") ? "crit" : "warn";
  return worstLevel([level, fromAnomalies]);
}
