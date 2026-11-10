import { describe, expect, it } from "vitest";
import { modelOpinionText } from "../modelOpinion";

describe("modelOpinionText", () => {
  it("diz quando o modelo concorda com a regra", () => {
    expect(modelOpinionText({ model_opinion: "anomalous" })).toBe(
      "O modelo de aprendizado de máquina também considerou esta leitura fora do normal deste computador.",
    );
  });

  it("explica a gravidade reduzida quando o modelo achou normal", () => {
    expect(modelOpinionText({ model_opinion: "normal", model_demoted: true })).toBe(
      "Para o modelo de aprendizado de máquina, esta leitura é normal neste computador, por isso a gravidade foi reduzida.",
    );
  });

  it("não sugere engano quando a regra vê o que o modelo não avalia", () => {
    expect(modelOpinionText({ model_opinion: "normal" })).toBe(
      "Para o modelo de aprendizado de máquina, o computador como um todo está normal. " +
        "Este aviso vem de uma regra que observa algo que o modelo não avalia, como um programa específico.",
    );
  });

  it("sem opinião do modelo não mostra nada", () => {
    expect(modelOpinionText(undefined)).toBeNull();
    expect(modelOpinionText({})).toBeNull();
  });
});
