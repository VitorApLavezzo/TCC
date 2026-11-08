import { describe, expect, it } from "vitest";

/**
 * Opacidade de cor fora da escala do Tailwind não vira CSS nenhum: `bg-crit/8`
 * compila sem aviso e não gera regra (a escala só tem 0, 5, 10… 100). Valor
 * fora da escala vai entre colchetes: `bg-crit/[.08]`.
 */
const SCALE = new Set([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]);

const sources = import.meta.glob("../../**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<
  string,
  string
>;

const OPACITY_CLASS =
  /\b(?:bg|text|border|ring|ring-offset|from|via|to|fill|stroke|outline|divide|shadow|decoration|placeholder|caret)-[a-z][a-z0-9-]*\/(\d+)\b/g;

describe("opacidade de cor nas classes", () => {
  it("só usa passos que o Tailwind gera", () => {
    const offScale: string[] = [];
    for (const [file, text] of Object.entries(sources)) {
      if (file.includes("__tests__")) continue;
      for (const m of text.matchAll(OPACITY_CLASS)) {
        if (!SCALE.has(Number(m[1]))) offScale.push(`${file}: ${m[0]}`);
      }
    }
    expect(offScale).toEqual([]);
  });
});
