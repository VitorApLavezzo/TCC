import { describe, expect, it } from "vitest";
import { ANOMALY_TYPE_LABELS } from "../../types";

/**
 * O mesmo aviso precisa ter o mesmo nome em toda parte: o backend escreve o
 * título das notificações, do e-mail e da linha do tempo; o frontend, o da
 * lista de avisos.
 */
const backend = import.meta.glob("../../../../backend/app/core/labels.py", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

function backendLabels(text: string): Record<string, string> {
  const block = text.split("ANOMALY_TYPE_LABELS = {")[1]?.split("\n}")[0] ?? "";
  return Object.fromEntries([...block.matchAll(/"(\w+)":\s*"([^"]+)"/g)].map((m) => [m[1], m[2]]));
}

describe("nomes dos avisos", () => {
  const source = Object.values(backend)[0];

  // No build do Docker só a pasta do frontend existe; lá não há o que comparar.
  it.skipIf(!source)("são os mesmos no frontend e no backend", () => {
    expect(ANOMALY_TYPE_LABELS).toEqual(backendLabels(source));
  });

  it("começam com maiúscula e seguem em minúscula, como frase", () => {
    // "Disco Quase Cheio" é convenção do inglês; em português é "Disco quase cheio".
    const titleCased = Object.values(ANOMALY_TYPE_LABELS).filter((r) => /\s[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]/.test(r));
    expect(titleCased).toEqual([]);
  });
});
