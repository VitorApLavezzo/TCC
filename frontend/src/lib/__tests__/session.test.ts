import { describe, expect, it } from "vitest";
import { loginErrorMessage, sessionExpired } from "../session";

/**
 * Quando um 401 significa "sua sessão expirou": quem nunca entrou (/register,
 * link do técnico) também recebe 401 de chamadas de fundo.
 */
describe("sessionExpired", () => {
  it("expira quando havia sessão e o servidor recusou", () => {
    expect(sessionExpired({ hadToken: true, pathname: "/machines" })).toBe(true);
  });

  it("não expira o que nunca existiu: visitante sem token numa página pública", () => {
    expect(sessionExpired({ hadToken: false, pathname: "/register" })).toBe(false);
    expect(sessionExpired({ hadToken: false, pathname: "/compartilhado/abc" })).toBe(false);
  });

  it("não redireciona quem já está no login", () => {
    expect(sessionExpired({ hadToken: true, pathname: "/login" })).toBe(false);
  });
});

describe("loginErrorMessage", () => {
  it("só culpa a senha quando o servidor recusou a senha", () => {
    expect(loginErrorMessage(401)).toBe("Usuário ou senha incorretos.");
  });

  it("explica o limite de tentativas em vez de culpar a senha", () => {
    expect(loginErrorMessage(429)).toMatch(/tentativas/);
  });

  it("separa falha do servidor de senha errada", () => {
    expect(loginErrorMessage(500)).toMatch(/servidor/);
    expect(loginErrorMessage(500)).not.toMatch(/senha/);
  });

  it("sem resposta, a culpa é da conexão", () => {
    expect(loginErrorMessage(undefined)).toMatch(/falar com o servidor/);
  });
});
