/** O que o modelo de aprendizado de máquina achou da leitura de um aviso de regra. */
export function modelOpinionText(behavior?: { model_opinion?: string; model_demoted?: boolean }): string | null {
  if (behavior?.model_opinion === "anomalous") {
    return "O modelo de aprendizado de máquina também considerou esta leitura fora do normal deste computador.";
  }
  if (behavior?.model_opinion === "normal") {
    return behavior.model_demoted
      ? "Para o modelo de aprendizado de máquina, esta leitura é normal neste computador, por isso a gravidade foi reduzida."
      : "Para o modelo de aprendizado de máquina, o computador como um todo está normal. " +
          "Este aviso vem de uma regra que observa algo que o modelo não avalia, como um programa específico.";
  }
  return null;
}
