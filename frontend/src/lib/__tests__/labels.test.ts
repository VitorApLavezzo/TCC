import { describe, expect, it } from "vitest";
import { ANOMALY_TYPE_LABELS } from "../../types";

/**
 * O mesmo aviso precisa ter o mesmo nome em toda parte.
 *
 * O backend escreve o título das notificações, do e-mail e da linha do tempo;
 * o frontend escreve o da lista de avisos. Os dois dicionários tinham
 * divergido, e um mesmo aviso aparecia como "Processo em Loop Infinito (CPU
 * Travada)" numa tela e "Programa travado consumindo o processador" em outra.
 */
const backend = import.meta.glob("../../../../backend/app/core/labels.py", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

function rotulosDoBackend(texto: string): Record<string, string> {
  const bloco = texto.split("ANOMALY_TYPE_LABELS = {")[1]?.split("\n}")[0] ?? "";
  return Object.fromEntries([...bloco.matchAll(/"(\w+)":\s*"([^"]+)"/g)].map((m) => [m[1], m[2]]));
}

describe("nomes dos avisos", () => {
  const fonte = Object.values(backend)[0];

  // No build do Docker só a pasta do frontend existe; lá não há o que comparar.
  it.skipIf(!fonte)("são os mesmos no frontend e no backend", () => {
    expect(ANOMALY_TYPE_LABELS).toEqual(rotulosDoBackend(fonte));
  });

  it("começam com maiúscula e seguem em minúscula, como frase", () => {
    // "Disco Quase Cheio" é convenção do inglês; em português é "Disco quase cheio".
    const titulo = Object.values(ANOMALY_TYPE_LABELS).filter((r) => /\s[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]/.test(r));
    expect(titulo).toEqual([]);
  });
});
