import type { Policy } from "../types";

/**
 * Substitui na frase os números que o servidor decide.
 *
 * "100 leituras e 1 hora", "a cada 10 a 60 segundos": são rótulos prontos,
 * vindos do servidor, porque plural é formatação e formatação mora num lugar
 * só. A tela escreve a frase ao redor e não sabe nenhum número.
 *
 * Devolve `null` quando a frase depende de um número que ainda não chegou —
 * nunca o marcador cru. Guardar uma cópia dos valores aqui "para o caso de não
 * carregar" recriaria exatamente a divergência que isto veio resolver.
 */
const MARCADOR = /\{([a-z_]+)\}/g;

export function fillPolicy(text: string, policy: Policy | null): string | null {
  if (!MARCADOR.test(text)) {
    MARCADOR.lastIndex = 0;
    return text;
  }
  MARCADOR.lastIndex = 0;
  if (!policy) return null;
  return text.replace(MARCADOR, (cru, chave: string) => {
    const secao = (policy as unknown as Record<string, { rotulo?: string }>)[chave];
    return secao?.rotulo ?? cru;
  });
}
