import type { LearningStatus } from "../types";

/**
 * A máquina ainda está conhecendo o próprio normal?
 *
 * Decide o cartão de progresso, a frase do rodapé e se vale continuar
 * buscando o estado no servidor. Estava escrita igual em dois arquivos.
 *
 * O veredito é do servidor (`learning`), que considera as duas réguas —
 * leituras e horas de relógio. `ml_ready` é só a reserva para agente ou
 * servidor antigo, de antes de o campo existir: olhar só para o modelo diria
 * "já aprendeu" numa máquina que tem leituras suficientes e meia hora de vida.
 */
export function stillLearning(status: LearningStatus | null | undefined): boolean {
  if (!status) return false;
  return status.learning ?? !status.ml_ready;
}
