/**
 * Faixas de saúde por métrica: todo número do painel passa por aqui, para a
 * pessoa não precisar saber que 94% de CPU é ruim e 12% é bom.
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
 * `border` acompanha essa tinta; `borderStrong` é a cor cheia, para quando
 * a borda carrega o significado sozinha, sem fundo atrás.
 */
export const LEVEL_CLASS: Record<
  Level,
  { text: string; bg: string; border: string; borderStrong: string; fill: string }
> = {
  ok: { text: "text-ok", bg: "bg-ok/[.08]", border: "border-ok/30", borderStrong: "border-ok", fill: "bg-ok" },
  warn: { text: "text-warn", bg: "bg-warn/[.08]", border: "border-warn/30", borderStrong: "border-warn", fill: "bg-warn" },
  crit: { text: "text-crit", bg: "bg-crit/[.08]", border: "border-crit/30", borderStrong: "border-crit", fill: "bg-crit" },
  unknown: {
    text: "text-fg-2",
    bg: "bg-sunken",
    border: "border-hairline",
    // `edge` e não `hairline`: numa barra de 2px o filete some contra o fundo,
    // e severidade baixa continua precisando ser vista para ser dispensada.
    borderStrong: "border-edge",
    fill: "bg-fg-3",
  },
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

/**
 * Limites de cada medida. São os mesmos números que decidem o rótulo de
 * estado e a faixa do normal desenhada atrás do traço.
 */
export const THRESHOLDS: Record<string, { warn: number; crit: number; max: number }> = {
  cpu: { warn: 80, crit: 92, max: 100 },
  memory: { warn: 85, crit: 94, max: 100 },
  disk: { warn: 85, crit: 95, max: 100 },
  swap: { warn: 40, crit: 75, max: 100 },
  cpuTemp: { warn: 75, crit: 88, max: 100 },
  gpuTemp: { warn: 80, crit: 90, max: 100 },
  gpuLoad: { warn: 90, crit: 97, max: 100 },
  gpuMemory: { warn: 88, crit: 96, max: 100 },
};

/** Faixa normal de uma medida, no formato que o SignalTrace desenha. */
export function bandFor(metric: keyof typeof THRESHOLDS): { from: number; to: number } | null {
  const t = THRESHOLDS[metric];
  return t ? { from: 0, to: t.warn } : null;
}

function byThreshold(value: number | null | undefined, warn: number, crit: number): Reading {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return { level: "unknown", label: LEVEL_LABEL.unknown };
  }
  const level: Level = value >= crit ? "crit" : value >= warn ? "warn" : "ok";
  return { level, label: LEVEL_LABEL[level] };
}

function rated(metric: keyof typeof THRESHOLDS) {
  const t = THRESHOLDS[metric];
  return (v?: number | null) => byThreshold(v, t.warn, t.crit);
}

export const health = {
  cpu: rated("cpu"),
  memory: rated("memory"),
  disk: rated("disk"),
  swap: rated("swap"),
  cpuTemp: rated("cpuTemp"),
  gpuTemp: rated("gpuTemp"),
  gpuLoad: rated("gpuLoad"),
  gpuMemory: rated("gpuMemory"),

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
