import { describe, expect, it } from "vitest";

/**
 * Opacidade de cor fora da escala do Tailwind não vira CSS nenhum.
 *
 * `bg-crit/8` parece certo, compila sem aviso e não gera regra: a escala
 * padrão só tem 0, 5, 10, 15… 100. As caixas de erro e de aviso ficaram sem
 * fundo por causa disso. Valor fora da escala vai entre colchetes:
 * `bg-crit/[.08]`.
 */
const ESCALA = new Set([0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]);

const fontes = import.meta.glob("../../**/*.{ts,tsx}", { query: "?raw", import: "default", eager: true }) as Record<
  string,
  string
>;

const CLASSE_COM_OPACIDADE =
  /\b(?:bg|text|border|ring|ring-offset|from|via|to|fill|stroke|outline|divide|shadow|decoration|placeholder|caret)-[a-z][a-z0-9-]*\/(\d+)\b/g;

describe("opacidade de cor nas classes", () => {
  it("só usa passos que o Tailwind gera", () => {
    const fora: string[] = [];
    for (const [arquivo, texto] of Object.entries(fontes)) {
      if (arquivo.includes("__tests__")) continue;
      for (const m of texto.matchAll(CLASSE_COM_OPACIDADE)) {
        if (!ESCALA.has(Number(m[1]))) fora.push(`${arquivo}: ${m[0]}`);
      }
    }
    expect(fora).toEqual([]);
  });
});
