import { describe, expect, it } from "vitest";
import { isNotFound } from "../http";

/**
 * "Não existe" só quando o servidor disse que não existe. Antes, qualquer
 * falha — rede caída, servidor reiniciando — virava "este aviso não existe
 * mais", e a pessoa concluía uma coisa falsa.
 */
describe("isNotFound", () => {
  it("é 'não existe' quando o servidor respondeu 404", () => {
    expect(isNotFound({ response: { status: 404 } })).toBe(true);
  });

  it("falha de rede ou de servidor não é 'não existe'", () => {
    expect(isNotFound({})).toBe(false);
    expect(isNotFound({ response: { status: 500 } })).toBe(false);
    expect(isNotFound(undefined)).toBe(false);
  });
});
