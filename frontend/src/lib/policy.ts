import type { Policy } from "../types";

/**
 * Substitui na frase os números que o servidor decide ("100 leituras e 1 hora"
 * chega pronto como `rotulo`). Devolve `null` quando a frase depende de um
 * número que ainda não chegou, nunca o marcador cru; não há cópia local dos
 * valores de propósito, para a tela nunca divergir do servidor.
 */
const PLACEHOLDER = /\{([a-z_]+)\}/g;

export function fillPolicy(text: string, policy: Policy | null): string | null {
  if (!PLACEHOLDER.test(text)) {
    PLACEHOLDER.lastIndex = 0;
    return text;
  }
  PLACEHOLDER.lastIndex = 0;
  if (!policy) return null;
  return text.replace(PLACEHOLDER, (raw, key: string) => {
    const section = (policy as unknown as Record<string, { rotulo?: string }>)[key];
    return section?.rotulo ?? raw;
  });
}
