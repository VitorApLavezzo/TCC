import { afterEach, describe, expect, it, vi } from "vitest";
import { killParamsFor } from "../actions";
import { stopPushOnThisDevice } from "../push";

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

describe("stopPushOnThisDevice", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sair da conta tira a assinatura deste aparelho no servidor e no navegador", async () => {
    const subscription = { endpoint: "https://fcm.googleapis.com/fcm/send/x", unsubscribe: vi.fn(async () => true) };
    vi.stubGlobal("navigator", {
      serviceWorker: { getRegistration: async () => ({ pushManager: { getSubscription: async () => subscription } }) },
    });
    const server = vi.fn(async () => undefined);
    await stopPushOnThisDevice(server);
    expect(server).toHaveBeenCalledWith("https://fcm.googleapis.com/fcm/send/x");
    expect(subscription.unsubscribe).toHaveBeenCalled();
  });

  it("sem service worker não quebra a saída", async () => {
    vi.stubGlobal("navigator", {});
    await expect(stopPushOnThisDevice(vi.fn())).resolves.toBeUndefined();
  });
});
