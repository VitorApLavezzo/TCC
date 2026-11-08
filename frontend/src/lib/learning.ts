import type { LearningStatus } from "../types";

/**
 * A máquina ainda está conhecendo o próprio normal?
 *
 * O veredito é do servidor (`learning`), que considera leituras e horas de
 * relógio. `ml_ready` é só a reserva para servidor antigo, sem o campo: olhar
 * só para o modelo diria "já aprendeu" numa máquina com meia hora de vida.
 */
export function stillLearning(status: LearningStatus | null | undefined): boolean {
  if (!status) return false;
  return status.learning ?? !status.ml_ready;
}
