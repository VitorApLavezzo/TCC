/**
 * Tira a assinatura de avisos deste aparelho.
 *
 * Sair da conta só apagava o token: a assinatura de push continuava no
 * navegador e no servidor, presa à conta antiga. Num computador
 * compartilhado, os avisos dela seguiam aparecendo para quem entrasse depois.
 * `avisarServidor` recebe o endereço da assinatura para apagá-la lá também;
 * se não houver rede, o servidor a descarta na primeira entrega recusada.
 */
export async function pararAvisosNesteAparelho(
  avisarServidor?: (endpoint: string) => Promise<unknown>,
): Promise<void> {
  try {
    if (typeof navigator === "undefined" || !navigator.serviceWorker) return;
    const registro = await navigator.serviceWorker.getRegistration();
    const assinatura = await registro?.pushManager?.getSubscription();
    if (!assinatura) return;
    if (avisarServidor) {
      try {
        await avisarServidor(assinatura.endpoint);
      } catch {
        // sem rede ou sessão já vencida: o servidor apaga no próximo 410
      }
    }
    await assinatura.unsubscribe();
  } catch {
    // navegador sem suporte a push: não há o que desligar
  }
}
