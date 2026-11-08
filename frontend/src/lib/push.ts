/**
 * Tira a assinatura de push deste aparelho. Sem isso, num computador
 * compartilhado, os avisos da conta antiga seguiam chegando a quem entrasse
 * depois. `notifyServer` recebe o endpoint para apagá-la no servidor também;
 * sem rede, o servidor a descarta na primeira entrega recusada.
 */
export async function stopPushOnThisDevice(
  notifyServer?: (endpoint: string) => Promise<unknown>,
): Promise<void> {
  try {
    if (typeof navigator === "undefined" || !navigator.serviceWorker) return;
    const registration = await navigator.serviceWorker.getRegistration();
    const subscription = await registration?.pushManager?.getSubscription();
    if (!subscription) return;
    if (notifyServer) {
      try {
        await notifyServer(subscription.endpoint);
      } catch {
        // sem rede ou sessão já vencida: o servidor apaga no próximo 410
      }
    }
    await subscription.unsubscribe();
  } catch {
    // navegador sem suporte a push: não há o que desligar
  }
}
