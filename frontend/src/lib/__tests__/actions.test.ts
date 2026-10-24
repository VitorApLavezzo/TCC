import { describe, expect, it } from "vitest";
import { confirmBody } from "../actions";

/**
 * A confirmação antes de uma ação remota precisa dizer a verdade sobre o que
 * dá para desfazer. Antes, toda ação perigosa prometia "você pode reverter
 * depois pelo painel" — inclusive encerrar um programa e apagar temporários.
 */
describe("confirmBody", () => {
  it("não promete desfazer o que não tem volta", () => {
    expect(confirmBody("kill_process", "PC-Sala")).not.toMatch(/reverter|desfazer/i);
    expect(confirmBody("clean_temp", "PC-Sala")).not.toMatch(/reverter|desfazer/i);
  });

  it("diz como desfazer quando dá", () => {
    expect(confirmBody("isolate_network", "PC-Sala")).toMatch(/Restaurar a rede/);
  });

  it("nomeia o computador", () => {
    expect(confirmBody("kill_process", "PC-Sala")).toContain("PC-Sala");
  });
});
