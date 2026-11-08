import { describe, expect, it } from "vitest";
import { bulkResolveMessage, confirmBody, hasAnomalyActions } from "../actions";

/**
 * A confirmação antes de uma ação remota precisa dizer a verdade sobre o que
 * dá para desfazer.
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

describe("bulkResolveMessage", () => {
  it("concorda o particípio com a quantidade", () => {
    expect(bulkResolveMessage(1, false)).toBe("1 aviso resolvido.");
    expect(bulkResolveMessage(2, false)).toBe("2 avisos resolvidos.");
    expect(bulkResolveMessage(3, true)).toBe("3 avisos reabertos.");
  });
});

describe("hasAnomalyActions", () => {
  const machine = { network_isolated: false } as any;
  const anomaly = (type: string, extra: Record<string, any> = {}) =>
    ({ anomaly_type: type, responsible_process: null, affected_metrics: {}, ...extra }) as any;

  it("não oferece a seção sem nenhuma ação possível", () => {
    expect(hasAnomalyActions(anomaly("cpu_spike"), machine)).toBe(false);
    expect(hasAnomalyActions(anomaly("cpu_spike"), null)).toBe(false);
  });

  it("oferece quando há o que fazer", () => {
    expect(hasAnomalyActions(anomaly("disk_full"), machine)).toBe(true);
    expect(hasAnomalyActions(anomaly("network_spike"), machine)).toBe(true);
    expect(hasAnomalyActions(anomaly("cpu_spike", { affected_metrics: { _behavior: { pid: 42 } } }), machine)).toBe(true);
    expect(hasAnomalyActions(anomaly("cpu_spike"), { network_isolated: true } as any)).toBe(true);
  });
});
