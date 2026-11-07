import { afterEach, describe, expect, it, vi } from "vitest";
import { killParamsFor } from "../actions";
import { pararAvisosNesteAparelho } from "../push";

/**
 * Regressões da auditoria de segurança (run-1) no painel.
 */
describe("killParamsFor", () => {
  it("manda a identidade da instância para o agente conferir", () => {
    const beh = { pid: 4242, exe: "C:\\Users\\bob\\svchost.exe", create_time: 1700000000 };
    expect(killParamsFor("svchost.exe", beh)).toEqual({
      pid: 4242,
      name: "svchost.exe",
      exe: "C:\\Users\\bob\\svchost.exe",
      create_time: 1700000000,
    });
  });

  it("sem pid não há o que encerrar com segurança", () => {
    // Só com o nome, o agente encerraria todos os processos homônimos
    expect(killParamsFor("svchost.exe", {})).toBeNull();
  });
});

describe("pararAvisosNesteAparelho", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sair da conta tira a assinatura deste aparelho no servidor e no navegador", async () => {
    const assinatura = { endpoint: "https://fcm.googleapis.com/fcm/send/x", unsubscribe: vi.fn(async () => true) };
    vi.stubGlobal("navigator", {
      serviceWorker: { getRegistration: async () => ({ pushManager: { getSubscription: async () => assinatura } }) },
    });
    const servidor = vi.fn(async () => undefined);
    await pararAvisosNesteAparelho(servidor);
    expect(servidor).toHaveBeenCalledWith("https://fcm.googleapis.com/fcm/send/x");
    expect(assinatura.unsubscribe).toHaveBeenCalled();
  });

  it("sem service worker não quebra a saída", async () => {
    vi.stubGlobal("navigator", {});
    await expect(pararAvisosNesteAparelho(vi.fn())).resolves.toBeUndefined();
  });
});
