import { describe, expect, it } from "vitest";
import { stillLearning } from "../learning";
import type { LearningStatus } from "../../types";

/**
 * "Ainda está aprendendo?" decide três coisas na tela: o cartão de progresso,
 * a frase do rodapé e — desde o conserto do F5 — se vale continuar buscando o
 * estado no servidor. Estava escrita duas vezes, igual, em dois arquivos.
 */
const base: LearningStatus = { collected: 50, needed: 100, ml_ready: false, retrain_every: 30 };

describe("stillLearning", () => {
  it("sem estado nenhum, não afirma que está aprendendo", () => {
    expect(stillLearning(null)).toBe(false);
    expect(stillLearning(undefined)).toBe(false);
  });

  it("usa o veredito do servidor quando ele vem", () => {
    expect(stillLearning({ ...base, learning: true })).toBe(true);
    expect(stillLearning({ ...base, learning: false, ml_ready: false })).toBe(false);
  });

  it("servidor antigo sem o campo cai para o estado do modelo", () => {
    expect(stillLearning({ ...base, ml_ready: false })).toBe(true);
    expect(stillLearning({ ...base, ml_ready: true })).toBe(false);
  });

  it("o veredito do servidor ganha do estado do modelo", () => {
    // Modelo treinado mas ainda faltando horas de relógio: está aprendendo.
    expect(stillLearning({ ...base, learning: true, ml_ready: true })).toBe(true);
  });
});
