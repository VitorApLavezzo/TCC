/**
 * Faixas de saúde por métrica.
 *
 * Todo número que aparece no painel passa por aqui antes de ir para a tela.
 * Sem isso o usuário precisa já saber que 94% de CPU é ruim e 12% é bom —
 * que é exatamente o conhecimento que ele não tem.
 */

export type Level = "ok" | "warn" | "crit" | "unknown";

export interface Reading {
  level: Level;
  /** Rótulo curto exibido embaixo do número. */
  label: string;
}

const LEVEL_LABEL: Record<Level, string> = {
  ok: "normal",
  warn: "atenção",
  crit: "crítico",
  unknown: "sem dados",
};

/**
 * Um único lugar decide a cor de cada nível.
 *
 * `bg` é uma tinta de 8% em vez de um tom sólido: fundo colorido é usado só
 * na faixa de urgência de um aviso, nunca como preenchimento de painel.
 */
export const LEVEL_CLASS: Record<Level, { text: string; bg: string; border: string; fill: string }> = {
  ok: { text: "text-ok", bg: "bg-ok/8", border: "border-ok/30", fill: "bg-ok" },
  warn: { text: "text-warn", bg: "bg-warn/8", border: "border-warn/30", fill: "bg-warn" },
  crit: { text: "text-crit", bg: "bg-crit/8", border: "border-crit/30", fill: "bg-crit" },
  unknown: { text: "text-fg-3", bg: "bg-sunken", border: "border-hairline", fill: "bg-fg-3" },
};

export function levelLabel(level: Level) {
  return LEVEL_LABEL[level];
}

/**
 * Nível de uma leitura no formato que os componentes de exibição aceitam.
 * "unknown" vira `undefined`: sem leitura não há cor a aplicar.
 */
export function toneOf(reading: Reading): "ok" | "warn" | "crit" | undefined {
  return reading.level === "unknown" ? undefined : reading.level;
}

/** Pior nível de um conjunto — usado para o veredito da máquina. */
export function worstLevel(levels: Level[]): Level {
  if (levels.includes("crit")) return "crit";
  if (levels.includes("warn")) return "warn";
  if (levels.includes("ok")) return "ok";
  return "unknown";
}

function byThreshold(value: number | null | undefined, warn: number, crit: number): Reading {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return { level: "unknown", label: LEVEL_LABEL.unknown };
  }
  const level: Level = value >= crit ? "crit" : value >= warn ? "warn" : "ok";
  return { level, label: LEVEL_LABEL[level] };
}

export const health = {
  cpu: (v?: number | null) => byThreshold(v, 80, 92),
  memory: (v?: number | null) => byThreshold(v, 85, 94),
  disk: (v?: number | null) => byThreshold(v, 85, 95),
  swap: (v?: number | null) => byThreshold(v, 40, 75),
  cpuTemp: (v?: number | null) => byThreshold(v, 75, 88),
  gpuTemp: (v?: number | null) => byThreshold(v, 80, 90),
  gpuLoad: (v?: number | null) => byThreshold(v, 90, 97),
  gpuMemory: (v?: number | null) => byThreshold(v, 88, 96),

  /** Bateria e saúde de bateria invertem: quanto menor, pior. */
  battery: (v?: number | null): Reading => {
    if (v === null || v === undefined) return { level: "unknown", label: LEVEL_LABEL.unknown };
    const level: Level = v < 15 ? "crit" : v < 35 ? "warn" : "ok";
    return { level, label: level === "ok" ? "normal" : level === "warn" ? "carga baixa" : "quase acabando" };
  },
  batteryHealth: (v?: number | null): Reading => {
    if (v === null || v === undefined) return { level: "unknown", label: LEVEL_LABEL.unknown };
    const level: Level = v < 50 ? "crit" : v < 80 ? "warn" : "ok";
    return {
      level,
      label: level === "ok" ? "boa" : level === "warn" ? "desgastada" : "considere trocar",
    };
  },

  /**
   * Load average só faz sentido relativo ao número de núcleos: 4,0 é normal
   * num processador de 8 núcleos e crítico num de 2.
   */
  loadAvg: (v?: number | null, cores?: number | null): Reading => {
    if (v === null || v === undefined) return { level: "unknown", label: LEVEL_LABEL.unknown };
    const n = cores && cores > 0 ? cores : 4;
    const ratio = v / n;
    const level: Level = ratio >= 1.5 ? "crit" : ratio >= 0.9 ? "warn" : "ok";
    return {
      level,
      label: level === "ok" ? "folgado" : level === "warn" ? "no limite" : "sobrecarregado",
    };
  },
};
