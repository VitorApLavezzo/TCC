/**
 * Decisões sobre sessão, separadas do axios para poderem ser testadas.
 */

/**
 * Um 401 só quer dizer "sua sessão expirou" se havia sessão. Sem token, é
 * uma chamada de fundo numa página pública (cadastro, link do técnico) e
 * mandar a pessoa para o login com essa frase seria mentira.
 */
export function sessionExpired({ hadToken, pathname }: { hadToken: boolean; pathname: string }) {
  return hadToken && !pathname.startsWith("/login");
}

/** O motivo de o login não ter dado certo, pelo código da resposta. */
export function loginErrorMessage(status?: number) {
  if (status === undefined) return "Não conseguimos falar com o servidor. Verifique se ele está ligado.";
  if (status === 401) return "Usuário ou senha incorretos.";
  if (status === 429) return "Muitas tentativas seguidas. Espere alguns minutos e tente de novo.";
  if (status >= 500) return "O servidor teve um problema agora. Tente de novo em instantes.";
  return "Não foi possível entrar. Confira os dados e tente de novo.";
}
