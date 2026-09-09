/**
 * Barramento de saúde da conexão com o servidor.
 *
 * Os interceptors do axios avisam aqui em cada resposta, então qualquer
 * requisição do app alimenta o indicador — nenhuma página precisa se lembrar
 * de reportar. Antes, uma falha de rede era completamente silenciosa: o
 * painel seguia mostrando os números velhos como se fossem atuais.
 */

export interface ConnectionState {
  /** Última resposta do servidor foi bem-sucedida? `null` = ainda não sabemos. */
  reachable: boolean | null;
  /** Momento da última resposta bem-sucedida. */
  lastSuccessAt: number | null;
  /** Falhas consecutivas desde a última resposta boa. */
  consecutiveFailures: number;
}

let state: ConnectionState = {
  reachable: null,
  lastSuccessAt: null,
  consecutiveFailures: 0,
};

const listeners = new Set<(s: ConnectionState) => void>();

function emit() {
  for (const fn of listeners) fn(state);
}

export function reportSuccess() {
  const wasDown = state.reachable === false;
  state = { reachable: true, lastSuccessAt: Date.now(), consecutiveFailures: 0 };
  if (wasDown || state.lastSuccessAt !== null) emit();
}

export function reportFailure() {
  state = {
    ...state,
    reachable: false,
    consecutiveFailures: state.consecutiveFailures + 1,
  };
  emit();
}

export function getConnection() {
  return state;
}

export function subscribeConnection(fn: (s: ConnectionState) => void) {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
}
