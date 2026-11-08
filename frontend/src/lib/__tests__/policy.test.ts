import { describe, expect, it } from "vitest";
import { GLOSSARY } from "../glossary";
import { fillPolicy } from "../policy";
import type { Policy } from "../../types";

/** Os números de política vêm do servidor; estes testes guardam a substituição. */
const POLICY: Policy = {
  aprendizado: { leituras: 100, horas: 1, rotulo: "100 leituras e 1 hora" },
  coleta: { rapido_segundos: 10, normal_segundos: 30, lento_segundos: 60, rotulo: "a cada 10 a 60 segundos" },
  codigo_pareamento: { minutos: 30, rotulo: "30 minutos" },
};

describe("fillPolicy", () => {
  it("troca o marcador pelo que o servidor mandou", () => {
    expect(fillPolicy("ele espera {aprendizado} acompanhando", POLICY))
      .toBe("ele espera 100 leituras e 1 hora acompanhando");
  });

  it("troca mais de um marcador na mesma frase", () => {
    expect(fillPolicy("{coleta}, e o código vale {codigo_pareamento}", POLICY))
      .toBe("a cada 10 a 60 segundos, e o código vale 30 minutos");
  });

  it("acompanha a constante do servidor sem a tela saber o número", () => {
    const other: Policy = { ...POLICY, aprendizado: { leituras: 100, horas: 2, rotulo: "100 leituras e 2 horas" } };
    expect(fillPolicy("espera {aprendizado}", other)).toBe("espera 100 leituras e 2 horas");
  });

  it("sem política carregada, devolve nulo em vez de mostrar o marcador cru", () => {
    expect(fillPolicy("espera {aprendizado}", null)).toBeNull();
  });

  it("texto sem marcador aparece mesmo sem política", () => {
    expect(fillPolicy("Memória RAM é onde ficam os programas abertos.", null))
      .toBe("Memória RAM é onde ficam os programas abertos.");
  });

  it("marcador desconhecido não é substituído nem quebra a frase", () => {
    expect(fillPolicy("valor {inexistente} aqui", POLICY)).toBe("valor {inexistente} aqui");
  });
});

describe("glossário não guarda número de política", () => {
  // Número escrito no glossário não acompanha quando o servidor muda.
  it("fala do aprendizado pelo marcador, não pelo número", () => {
    expect(GLOSSARY.aprendizado).toContain("{aprendizado}");
    expect(GLOSSARY.aprendizado).not.toMatch(/\d+\s*(leituras?|horas?)/);
  });

  it("fala do ritmo de coleta pelo marcador", () => {
    expect(GLOSSARY.ao_vivo).toContain("{coleta}");
    expect(GLOSSARY.ao_vivo).not.toMatch(/\d+\s*segundos?/);
  });

  it("fala da validade do código pelo marcador", () => {
    expect(GLOSSARY.codigo_pareamento).toContain("{codigo_pareamento}");
    expect(GLOSSARY.codigo_pareamento).not.toMatch(/\d+\s*minutos?/);
  });
});
